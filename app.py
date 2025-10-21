import streamlit as st
import pandas as pd
from datetime import date, timedelta
import io
import re
import hashlib
import os

# File paths
SKU_FILE_PATH = "SKU Simulation.xlsx"
PLAN_FILE_PATH = "ProductionPlan.xlsx"

# Utility functions
def get_file_hash(filepath):
    """Generate hash of file to detect changes"""
    try:
        if os.path.exists(filepath):
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        st.warning(f"Could not generate hash for {filepath}: {e}")
    return None

def clean_string(series):
    """Clean string series (used for SKU and text fields)"""
    # Includes stripping non-breaking spaces (\xa0) and tabs (\t)
    return series.fillna("").astype(str).str.strip().str.replace('\xa0', '').str.replace('\t', '')

def clean_numeric_column(series):
    """
    Clean numeric column to handle common formatting issues:
    - Removes thousands separators (e.g., comma ',')
    - Strips all whitespace
    - Replaces non-breaking spaces
    """
    return series.astype(str).str.replace('\xa0', '').str.strip().str.replace('[,]', '', regex=True) # <-- NEW FUNCTION

def find_column(df, variations):
    """Find column from variations list"""
    df_cols = {col.strip().upper().replace('_', ' '): col for col in df.columns}
    for var in variations:
        if var in df_cols:
            return df_cols[var]
    return None

@st.cache_data(ttl=600)
def load_data(file_hash):
    """Load SKU master data"""
    try:
        df = pd.read_excel(SKU_FILE_PATH, sheet_name="Sheet1")
        st.info(f"📋 Columns found: {list(df.columns)}")
                
        # Column mapping
        required = {
            'SKU': ['SKU'],
            'MATERIAL': ['MATERIAL', 'MATERIAL NAME'],
            'QUANTITY': ['QUANTITY', 'QTY'],
            'TOTAL STOCK': ['TOTAL STOCK', 'TOTALSTOCK', 'STOCK', 'TOTAL_STOCK'],
            'MATERIAL DESCRIPTION': ['MATERIAL DESCRIPTION', 'MATERIALDESCRIPTION', 'MATERIAL_DESCRIPTION', 'DESCRIPTION', 'DESC'],
            'SUPPLIER NAME': ['SUPPLIER NAME', 'SUPPLIERNAME', 'SUPPLIER_NAME', 'SUPPLIER'],
            'MRP': ['MRP']
        }
                
        col_map = {}
        missing = []
                
        for target, variations in required.items():
            found_col = find_column(df, variations)
            if found_col:
                col_map[found_col] = target.replace(' ', '_').title().replace('_', ' ')
            else:
                missing.append(target)
                
        if missing:
            st.error(f"❌ Missing columns: {', '.join(missing)}")
            st.error(f"📋 Available: {list(df.columns)}")
            st.stop()
                
        df.rename(columns=col_map, inplace=True)
                
        # Clean data
        df["Sku"] = clean_string(df["Sku"])
        df["Material"] = df["Material"].astype(str).str.strip()
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0)
        df["Total Stock"] = pd.to_numeric(df["Total Stock"], errors="coerce").fillna(0)
                
        # Optional columns
        for col, warning in [("Material Description", "Material Description"), 
                             ("Supplier Name", "Supplier Name"), 
                             ("Mrp", "MRP")]:
            if col in df.columns:
                df[col] = df[col].fillna("").astype(str).str.strip().replace('nan', '')
            else:
                df[col] = ""
                st.warning(f"⚠️ '{warning}' not found. Using empty values.")
                
        df.rename(columns={"Sku": "SKU", "Mrp": "MRP"}, inplace=True)
        return df
            
    except Exception as e:
        st.error(f"Error loading SKU data: {e}")
        st.stop()

@st.cache_data(ttl=600)
def load_production_plan(file_hash, date_strings):
    """Load production plan from Excel"""
    try:
        # Assuming PLAN_FILE_PATH is correct and points to the Excel file
        plan = pd.read_excel(PLAN_FILE_PATH, sheet_name="Sheet1")
        return process_plan(plan, date_strings)
    except Exception as e:
        st.error(f"Error loading plan: {e}")
        return None

def process_plan(plan, date_strings):
    """Process uploaded plan"""
    st.info(f"🔍 Detected columns: {list(plan.columns)}")
        
    # Find SKU column
    sku_col = None
    for col in plan.columns:
        col_clean = re.sub(r'[^\w\s-]', '', str(col)).replace('\xa0', ' ').strip().upper()
        if any(kw in col_clean for kw in ['SKU', 'PRODUCTIONPLAN', 'PRODUCTION_PLAN', 'PRODUCTION PLAN']):
            sku_col = col
            break
            
    if not sku_col:
        st.error("❌ SKU column not found! Use: 'SKU', 'ProductionPlan', 'Production Plan'")
        return None
        
    st.success(f"✅ Found SKU column: '{sku_col}'")
        
    # Map columns
    col_map = {sku_col: "SKU"}
    date_cols_found = []
        
    for col in plan.columns:
        if col == sku_col:
            continue
        try:
            if isinstance(col, (pd.Timestamp, date)):
                date_str = pd.to_datetime(col).strftime("%Y-%m-%d")
                col_map[col] = date_str
                date_cols_found.append(date_str)
            else:
                parsed = pd.to_datetime(str(col), errors='coerce')
                if pd.notna(parsed):
                    date_str = parsed.strftime("%Y-%m-%d")
                    col_map[col] = date_str
                    date_cols_found.append(date_str)
                else:
                    col_map[col] = re.sub(r'[^\w\s-]', '', str(col)).strip()
        except:
            col_map[col] = re.sub(r'[^\w\s-]', '', str(col)).strip()
            
    st.info(f"📅 Date columns: {date_cols_found}")
        
    plan = plan.rename(columns=col_map)
    plan["SKU"] = clean_string(plan["SKU"])
        
    # Convert to numeric
    for col in plan.columns:
        if col != "SKU":
            # Only attempt to convert date-formatted columns to numeric
            if re.match(r'\d{4}-\d{2}-\d{2}', str(col)):
                # Apply the cleaning function before converting to numeric
                plan[col] = clean_numeric_column(plan[col]) # <-- FIX LINE
                plan[col] = pd.to_numeric(plan[col], errors="coerce").fillna(0)
            # Other non-date columns remain as is (they will be dropped later)
            
    # Ensure all date columns for the planning horizon exist, filling missing with 0.
    for d in date_strings:
        if d not in plan.columns:
            plan[d] = 0

    # Reindex the DataFrame to include only "SKU" and the full set of current date strings.
    plan = plan.reindex(columns=["SKU"] + date_strings, fill_value=0)
    
    plan = plan[plan["SKU"].str.strip() != ""]
        
    st.success(f"✅ Loaded: {len(plan)} rows, {len(plan.columns)} columns")
    return plan

def perform_mrp_run(plan_df, materials_df, dates):
    """Perform MRP calculation"""
    materials = materials_df["Material"].unique().tolist()
    mat_stock = materials_df.groupby("Material")["Total Stock"].first().to_dict()
    mat_desc = materials_df.groupby("Material")["Material Description"].first().to_dict()
    mat_supplier = materials_df.groupby("Material")["Supplier Name"].first().to_dict()
    mat_mrp = materials_df.groupby("Material")["MRP"].first().to_dict()

    mrp_df = pd.DataFrame(index=materials, columns=dates).fillna(0).astype(float)
    current_stock = {m: float(mat_stock.get(m, 0)) for m in materials}
    
    for date_str in dates:
        if date_str not in plan_df.columns:
            continue
            
        day_plan = plan_df[["SKU", date_str]].copy()
        day_plan.columns = ["SKU", "Planned Quantity"]
        day_plan["SKU"] = day_plan["SKU"].astype(str).str.strip()
        
        # Ensure quantities are numeric here again before filtering (safety check)
        day_plan["Planned Quantity"] = pd.to_numeric(day_plan["Planned Quantity"], errors="coerce").fillna(0)
        day_plan = day_plan[(day_plan["SKU"] != "") & (day_plan["Planned Quantity"] > 0)]
        
        if day_plan.empty:
            for m in materials:
                mrp_df.loc[m, date_str] = current_stock.get(m, 0)
            continue
            
        consumption = pd.merge(day_plan, materials_df, on="SKU", how="inner")
        
        if consumption.empty:
            for m in materials:
                mrp_df.loc[m, date_str] = current_stock.get(m, 0)
            continue
            
        consumption["Consumption"] = consumption["Planned Quantity"] * consumption["Quantity"]
        daily_cons = consumption.groupby("Material")["Consumption"].sum().to_dict()
        
        for m in materials:
            remaining = current_stock.get(m, 0) - daily_cons.get(m, 0)
            mrp_df.loc[m, date_str] = remaining
            current_stock[m] = remaining
            
    # Add info columns
    mrp_df.insert(0, "Total Stock", [float(mat_stock.get(m, 0)) for m in mrp_df.index])
    mrp_df.insert(0, "MRP", [str(mat_mrp.get(m, "")) for m in mrp_df.index])
    mrp_df.insert(0, "Supplier Name", [str(mat_supplier.get(m, "")) for m in mrp_df.index])
    mrp_df.insert(0, "Material Description", [str(mat_desc.get(m, "")) for m in mrp_df.index])
        
    return mrp_df

def update_plan_df(mode):
    """Update the appropriate plan dataframe"""
    df_key = "manual_plan_df" if mode == "Define manually" else "uploaded_plan_df"
    return df_key

def main():
    st.set_page_config(layout="wide")
    st.title("SKU Production Planner & MRP Run")
        
    # Refresh button
    col1, col2, col3 = st.columns([1.5, 1, 3.5])
    with col1:
        if st.button("🔄 Refresh Excel Files", type="secondary", key="refresh_excel_files_button"):
            st.cache_data.clear()
            st.success("✅ Cache cleared!")
            st.rerun()
    with col2:
        st.caption("Data loaded")
        
    # Load data
    sku_hash = get_file_hash(SKU_FILE_PATH)
    raw_materials_df = load_data(sku_hash)
    sku_list = raw_materials_df["SKU"].dropna().unique().tolist()
    st.success(f"✅ SKU data loaded from: {SKU_FILE_PATH}")
    
    # Date setup
    if "num_extra_dates" not in st.session_state:
        st.session_state.num_extra_dates = 0
        
    num_extra_dates = st.number_input("How many extra days to plan?", 0, 30, st.session_state.num_extra_dates, 1)
    st.session_state.num_extra_dates = num_extra_dates
    
    dates_list = [date.today() + timedelta(days=i) for i in range(num_extra_dates + 1)]
    date_strings = [d.strftime("%Y-%m-%d") for d in dates_list]
    
    # Input method
    st.subheader("Production Plan Input Method")
    plan_mode = st.radio("How would you like to provide the production plan?",
                         ["Define manually", "Upload from Excel"], horizontal=True)
                         
    # Initialize session state
    for key in ["manual_plan_df", "uploaded_plan_df", "matrix_df"]:
        if key not in st.session_state:
            st.session_state[key] = pd.DataFrame()
            
    # Manual mode
    if plan_mode == "Define manually":
        st.info("📝 **Manual Mode** - Create production plan from scratch")
                
        if st.session_state.manual_plan_df.empty:
            rows = st.number_input("How many SKU rows?", 1, 50, 5, 1)
            if st.button("Initialize Manual Plan", type="secondary"):
                st.session_state.manual_plan_df = pd.DataFrame({"SKU": [""] * rows, **{d: 0 for d in date_strings}})
                st.rerun()
        else:
            st.session_state.manual_plan_df = st.session_state.manual_plan_df.reindex(
                columns=["SKU"] + date_strings, fill_value=0)
            st.session_state.matrix_df = st.session_state.manual_plan_df.copy()
            
    # Excel mode
    else:
        st.info("📁 **Excel Mode** - Load production plan from Excel")
                
        col1, col2 = st.columns([1, 3])
        with col1:
            load_excel = st.button("📥 Load from Excel", type="secondary", key="load_excel_button")
        with col2:
            if not st.session_state.uploaded_plan_df.empty:
                st.success(f"✅ Excel data loaded ({len(st.session_state.uploaded_plan_df)} rows)")
                
        if load_excel:
            try:
                # Clear cache to force reload of the Excel file
                st.cache_data.clear()
                                
                plan_hash = get_file_hash(PLAN_FILE_PATH)
                processed = load_production_plan(plan_hash, date_strings)
                                
                if processed is not None:
                    st.session_state.uploaded_plan_df = processed
                    st.session_state.matrix_df = processed.copy()
                    st.success(f"✅ Plan loaded: {len(processed)} SKUs")
                    with st.expander("Preview"):
                        st.dataframe(processed.head(), use_container_width=True)
                    st.rerun()
            except FileNotFoundError:
                st.error(f"❌ File not found: {PLAN_FILE_PATH}")
            except Exception as e:
                st.error(f"❌ Error: {e}")
                
        # Set matrix_df if uploaded plan exists
        if not st.session_state.uploaded_plan_df.empty:
            st.session_state.matrix_df = st.session_state.uploaded_plan_df.copy()
            
    # Editable grid
    st.subheader(f"Production Plan (Editable) - {plan_mode}")
        
    if st.session_state.matrix_df.empty:
        msg = "📝 Click 'Initialize Manual Plan'" if plan_mode == "Define manually" else "📁 Click 'Load from Excel'"
        st.warning(f"{msg} to start.")
    else:
        # Ensure columns match
        st.session_state.matrix_df = st.session_state.matrix_df.reindex(
            columns=["SKU"] + date_strings, fill_value=0)
                
        for d in date_strings:
            st.session_state.matrix_df[d] = pd.to_numeric(
                st.session_state.matrix_df[d], errors="coerce").fillna(0).astype(int)
                
        # Row operations
        df_key = update_plan_df(plan_mode)
        current_df = st.session_state[df_key]
                
        col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
                
        with col1:
            if st.button("➕ Add Row"):
                new_row = pd.DataFrame({"SKU": [""], **{d: 0 for d in date_strings}})
                st.session_state[df_key] = pd.concat([current_df, new_row], ignore_index=True)
                st.session_state.matrix_df = st.session_state[df_key].copy()
                st.rerun()
                
        with col2:
            if st.button("➖ Remove Last Row") and len(current_df) > 1:
                st.session_state[df_key] = current_df.iloc[:-1]
                st.session_state.matrix_df = st.session_state[df_key].copy()
                st.rerun()
                
        with col3:
            if len(current_df) > 1:
                row_del = st.selectbox("Delete row:", list(range(len(current_df))),
                    format_func=lambda x: f"Row {x+1}: {current_df.iloc[x]['SKU'] or 'Empty'}")
                if st.button("🗑️ Delete Selected"):
                    st.session_state[df_key] = current_df.drop(index=row_del).reset_index(drop=True)
                    st.session_state.matrix_df = st.session_state[df_key].copy()
                    st.rerun()
                    
        if plan_mode == "Upload from Excel":
            st.info("💡 Click '🔄 Refresh Excel Files' to reload updated source file.")
            
        # Grid header
        header_cols = st.columns([3] + [1] * len(date_strings))
        header_cols[0].markdown("**SKU**")
        for i, d in enumerate(date_strings):
            header_cols[i + 1].markdown(f"**{d}**")
            
        # Grid rows
        sku_options = [""] + sku_list
        for row in range(len(st.session_state.matrix_df)):
            row_cols = st.columns([3] + [1] * len(date_strings))
                        
            current_sku = str(st.session_state.matrix_df.iloc[row]["SKU"]).strip()
            sku_idx = sku_options.index(current_sku) if current_sku in sku_options else 0
                        
            selected_sku = row_cols[0].selectbox("SKU", sku_options, sku_idx,
                                                  key=f"sku_{row}", label_visibility="collapsed")
            st.session_state[df_key].at[row, "SKU"] = selected_sku
                        
            for i, d in enumerate(date_strings):
                qty = int(st.session_state.matrix_df.iloc[row][d])
                qty_val = row_cols[i + 1].number_input(d, 0, step=1, value=qty,
                    key=f"qty_{row}_{d}", format="%d", label_visibility="collapsed")
                st.session_state[df_key].at[row, d] = qty_val
                
        # Download
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 2])
                
        with col1:
            download_df = st.session_state.matrix_df.copy()
            buffer = io.BytesIO()
            download_df.to_excel(buffer, index=False, sheet_name="ProductionPlan")
            buffer.seek(0)
            st.download_button("📥 Download Production Plan", buffer,
                f"ProductionPlan_{date.today().strftime('%Y%m%d')}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
                
        with col2:
            st.metric("Total SKUs", len(download_df[download_df['SKU'] != '']))
                
        with col3:
            total_qty = sum(download_df[d].sum() for d in date_strings if d in download_df.columns)
            st.metric("Total Production Quantity", f"{int(total_qty):,}")
            
    # Run MRP
    if st.button("Run MRP", type="primary"):
        if st.session_state.matrix_df.empty:
            st.warning("Please define or upload a production plan first.")
        else:
            with st.spinner("Performing MRP..."):
                st.session_state.mrp_result = perform_mrp_run(
                    st.session_state.matrix_df, raw_materials_df, date_strings)
            st.success("MRP run completed!")
            
    # Show results
    if "mrp_result" in st.session_state and not st.session_state.mrp_result.empty:
        st.subheader("MRP Results: Remaining Raw Material Stock")
        col1, col2, col3 = st.columns([2, 1, 1])
                
        with col1:
            search = st.text_input("🔍 Search for Material/Part Number:",
                placeholder="Enter material name or part number...")
                
        with col2:
            sort_opt = st.selectbox("Sort by:",
                ["Negative Stock First", "Material Name (A-Z)", "Material Name (Z-A)",
                  "Total Stock (Low to High)", "Total Stock (High to Low)"])
                
        with col3:
            neg_only = st.checkbox("Show Only Negative Stock", False)
                
        display_df = st.session_state.mrp_result.copy()
        display_df.insert(0, 'Material', display_df.index)
                
        # Search filter
        if search:
            search_upper = search.upper()
            mask = (display_df['Material'].str.upper().str.contains(search_upper, na=False) |
                   display_df['Material Description'].str.upper().str.contains(search_upper, na=False) |
                   display_df['Supplier Name'].str.upper().str.contains(search_upper, na=False))
            display_df = display_df[mask]
                        
            if len(display_df) == 0:
                st.warning(f"⚠️ No results found for '{search}'")
            else:
                st.success(f"✅ Found {len(display_df)} material(s)")
                
        # Negative filter
        if neg_only:
            date_cols = [c for c in display_df.columns 
                         if c not in ['Material', 'Material Description', 'Supplier Name', 'MRP', 'Total Stock']]
            display_df = display_df[display_df[date_cols].lt(0).any(axis=1)]
                        
            if len(display_df) == 0:
                st.success("✅ No materials have negative stock.")
            else:
                st.warning(f"⚠️ {len(display_df)} material(s) with negative stock")
                
        # Sorting
        date_cols = [c for c in display_df.columns 
                     if c not in ['Material', 'Material Description', 'Supplier Name', 'MRP', 'Total Stock']]
                
        if sort_opt == "Negative Stock First" and date_cols:
            display_df['_min'] = display_df[date_cols].min(axis=1)
            display_df = display_df.sort_values('_min').drop(columns=['_min'])
        elif "Material Name" in sort_opt:
            display_df = display_df.sort_values('Material', ascending="A-Z" in sort_opt)
        elif "Total Stock" in sort_opt:
            display_df = display_df.sort_values('Total Stock', ascending="Low" in sort_opt)
                
        display_df = display_df.set_index('Material')
                
        # Stats
        if date_cols:
            neg_count = display_df[date_cols].lt(0).any(axis=1).sum()
            total_count = len(display_df)
                        
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Materials", total_count)
            c2.metric("Materials with Negative Stock", neg_count)
            c3.metric("✅ All Materials OK" if neg_count == 0 else "Materials OK",
                      total_count if neg_count == 0 else total_count - neg_count)
                
        # Display with highlighting
        def highlight(val):
            try:
                v = float(val)
                if v < 0: return "background-color: #ffcccc"
                if v == 0: return "background-color: #ffffcc"
            except: pass
            return ""
        st.dataframe(display_df.style.applymap(highlight), use_container_width=True, height=600)
        
        # Download results
        buffer = io.BytesIO()
        display_df.to_excel(buffer, index=True)
        buffer.seek(0)
        st.download_button("📥 Download MRP Results", buffer,
            f"MRP_Results_{date.today().strftime('%Y%m%d')}.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            
    # Clear data
    st.markdown("---")
    st.subheader("Data Management")
    c1, c2, c3 = st.columns(3)
        
    with c1:
        if st.button("🗑️ Clear Manual Plan", type="secondary"):
            st.session_state.manual_plan_df = pd.DataFrame()
            if plan_mode == "Define manually":
                st.session_state.matrix_df = pd.DataFrame()
            st.rerun()
            
    with c2:
        if st.button("🗑️ Clear Excel Plan", type="secondary"):
            st.session_state.uploaded_plan_df = pd.DataFrame()
            st.session_state.matrix_df = pd.DataFrame()
            st.cache_data.clear()  # Clear cache when clearing Excel plan
            st.success("Excel plan cleared.")
            st.rerun()
            
    with c3:
        if st.button("🗑️ Clear All Data", type="secondary"):
            for key in ["manual_plan_df", "uploaded_plan_df", "matrix_df", "mrp_result"]:
                if key in st.session_state:
                    if key == "mrp_result":
                        del st.session_state[key]
                    else:
                        st.session_state[key] = pd.DataFrame()
            st.session_state.num_extra_dates = 0
            st.rerun()

if __name__ == "__main__":
    main()

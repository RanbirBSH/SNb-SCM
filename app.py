import streamlit as st
import pandas as pd
from datetime import date, timedelta
import io
import re

# Fixed file paths
SKU_FILE_PATH = "SKU Simulation.xlsx"  
df = pd.read_excel(SKU_FILE_PATH)
PLAN_FILE_PATH = "ProductionPlan.xlsx"  
df = pd.read_excel(PLAN_FILE_PATH)

# Helper function for maximum string cleanup
def robust_string_clean(series):
    """Fills NaN, converts to string, strips visible space, and removes common hidden characters."""
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.replace('\xa0', '') # Remove non-breaking space
        .str.replace('\t', '')   # Remove tab character
    )

@st.cache_data
def load_data():
    """Loads SKU master data (SKU, Material, Quantity, Total Stock, Material Description, Supplier Name, MRP)."""
    try:
        df = pd.read_excel(SKU_FILE_PATH, sheet_name="Sheet1")
        
        # Display actual columns found in the file for debugging
        st.info(f"📋 Columns found in Excel file: {list(df.columns)}")
        
        # Robustly check for required columns with flexible matching
        df_cols_upper = {col.strip().upper().replace('_', ' '): col for col in df.columns}
        
        # Define required columns and their possible variations
        required_mappings = {
            'SKU': ['SKU'],
            'MATERIAL': ['MATERIAL', 'MATERIAL NAME'],
            'QUANTITY': ['QUANTITY', 'QTY'],
            'TOTAL STOCK': ['TOTAL STOCK', 'TOTALSTOCK', 'STOCK', 'TOTAL_STOCK'],
            'MATERIAL DESCRIPTION': ['MATERIAL DESCRIPTION', 'MATERIALDESCRIPTION', 'MATERIAL_DESCRIPTION', 'DESCRIPTION', 'DESC'],
            'SUPPLIER NAME': ['SUPPLIER NAME', 'SUPPLIERNAME', 'SUPPLIER_NAME', 'SUPPLIER'],
            'MRP': ['MRP']
        }
        
        # Find matching columns
        column_map = {}
        missing_columns = []
        
        for target_col, variations in required_mappings.items():
            found = False
            for variation in variations:
                if variation in df_cols_upper:
                    column_map[df_cols_upper[variation]] = target_col.replace(' ', '_').title().replace('_', ' ')
                    found = True
                    break
            if not found:
                missing_columns.append(target_col)
        
        if missing_columns:
            st.error(f"❌ Error: Could not find the following columns in the Excel file:")
            for col in missing_columns:
                possible_names = required_mappings[col]
                st.error(f"   • **{col}** (looking for any of: {', '.join(possible_names)})")
            st.error(f"")
            st.error(f"📋 **Actual columns in your file:** {list(df.columns)}")
            st.error(f"")
            st.error(f"💡 **Please ensure your Excel file contains these columns** (column names are case-insensitive)")
            st.stop()
        
        # Rename columns to standardized names
        df.rename(columns=column_map, inplace=True)
            
        # Apply robust cleaning to master SKU data
        df["Sku"] = robust_string_clean(df["Sku"])
        df["Material"] = df["Material"].astype(str).str.strip()
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0).astype(float)
        df["Total Stock"] = pd.to_numeric(df["Total Stock"], errors="coerce").fillna(0).astype(float)
        
        # Handle new columns with flexibility (they might not exist in older files)
        if "Material Description" in df.columns:
            df["Material Description"] = df["Material Description"].astype(str).str.strip()
        else:
            df["Material Description"] = ""
            st.warning("⚠️ 'Material Description' column not found. Using empty values.")
        
        if "Supplier Name" in df.columns:
            df["Supplier Name"] = df["Supplier Name"].astype(str).str.strip()
        else:
            df["Supplier Name"] = ""
            st.warning("⚠️ 'Supplier Name' column not found. Using empty values.")
        
        if "Mrp" in df.columns:
            # Keep MRP as text/string, not numeric
            df["Mrp"] = df["Mrp"].fillna("").astype(str).str.strip()
            # Remove 'nan' strings that might appear from conversion
            df["Mrp"] = df["Mrp"].replace('nan', '')
        else:
            df["Mrp"] = ""
            st.warning("⚠️ 'MRP' column not found. Using empty values.")
        
        # Rename back to consistent internal names
        df.rename(columns={
            "Sku": "SKU",
            "Mrp": "MRP"
        }, inplace=True)
        
        return df
    except Exception as e:
        st.error(f"Error loading SKU data: {e}")
        st.stop()

def perform_mrp_run(production_plan_df, raw_materials_df, dates_list):
    """Performs MRP run to calculate material consumption and remaining stock."""
    material_list = raw_materials_df["Material"].unique().tolist()
    material_stock = raw_materials_df.groupby("Material")["Total Stock"].sum().to_dict()
    
    # Create dictionaries for additional material information (keep MRP as string)
    material_description_dict = raw_materials_df.groupby("Material")["Material Description"].first().to_dict()
    supplier_name_dict = raw_materials_df.groupby("Material")["Supplier Name"].first().to_dict()
    material_mrp_dict = raw_materials_df.groupby("Material")["MRP"].first().to_dict()
    
    mrp_df = pd.DataFrame(index=material_list, columns=dates_list).fillna(0).astype(float)
    current_stock = {m: float(material_stock.get(m, 0.0)) for m in material_list}

    for date_str in dates_list:
        if date_str not in production_plan_df.columns:
            continue
        date_production = production_plan_df[["SKU", date_str]].copy()
        date_production.columns = ["SKU", "Planned Quantity"]
        
        # Ensure SKU column is clean for merging
        date_production["SKU"] = date_production["SKU"].astype(str).str.strip()
        
        date_production["Planned Quantity"] = pd.to_numeric(date_production["Planned Quantity"], errors="coerce").fillna(0)
        date_production = date_production[(date_production["SKU"] != "") & (date_production["Planned Quantity"] > 0)]

        if date_production.empty:
            for m in material_list:
                mrp_df.loc[m, date_str] = current_stock.get(m, 0.0)
            continue

        consumption_df = pd.merge(date_production, raw_materials_df, on="SKU", how="inner")
        if consumption_df.empty:
            for m in material_list:
                mrp_df.loc[m, date_str] = current_stock.get(m, 0.0)
            continue

        consumption_df["Consumption"] = consumption_df["Planned Quantity"] * consumption_df["Quantity"].astype(float)
        daily_consumption = consumption_df.groupby("Material")["Consumption"].sum().to_dict()

        next_stock = current_stock.copy()
        for m in material_list:
            consumed = daily_consumption.get(m, 0.0)
            prev = current_stock.get(m, 0.0)
            remaining = prev - consumed
            mrp_df.loc[m, date_str] = remaining
            next_stock[m] = remaining
        current_stock = next_stock

    # Add additional columns at the beginning (MRP is kept as string/text)
    mrp_df.insert(0, "Total Stock", [float(material_stock.get(m, 0.0)) for m in mrp_df.index])
    mrp_df.insert(0, "MRP", [str(material_mrp_dict.get(m, "")) for m in mrp_df.index])
    mrp_df.insert(0, "Supplier Name", [str(supplier_name_dict.get(m, "")) for m in mrp_df.index])
    mrp_df.insert(0, "Material Description", [str(material_description_dict.get(m, "")) for m in mrp_df.index])
    
    return mrp_df

def find_sku_column(uploaded_plan):
    """
    Enhanced function to find the SKU/ProductionPlan column with better matching logic
    """
    # Create a mapping of original column names to cleaned versions for analysis
    column_candidates = {}
    
    for col_original in uploaded_plan.columns:
        col_str = str(col_original).strip()
        
        # Remove common problematic characters and normalize
        col_clean = re.sub(r'[^\w\s-]', '', col_str)
        col_clean = col_clean.replace('\xa0', ' ').strip()
        col_clean_upper = col_clean.upper()
        
        # Check for SKU or ProductionPlan variations
        if any(keyword in col_clean_upper for keyword in ['SKU', 'PRODUCTIONPLAN', 'PRODUCTION_PLAN', 'PRODUCTION PLAN']):
            column_candidates[col_original] = col_clean
    
    # If we found candidates, return the first one (you can add more sophisticated logic here)
    if column_candidates:
        return list(column_candidates.keys())[0]
    
    # If no clear SKU column found, return None
    return None

def process_uploaded_plan(uploaded_plan, date_strings):
    """
    Process uploaded Excel plan with improved SKU column detection
    """
    # Debug: Show detected columns
    detected_cols_display = [str(c).strip() for c in uploaded_plan.columns]
    st.info(f"🔍 Detected columns: {detected_cols_display}")
    
    # Find the SKU column
    sku_column = find_sku_column(uploaded_plan)
    
    if sku_column is None:
        st.error("❌ **Could not find SKU column!** Please ensure your Excel file has a column with one of these names:")
        st.error("- 'SKU'")
        st.error("- 'ProductionPlan'") 
        st.error("- 'Production Plan'")
        st.error("- 'Production_Plan'")
        return None
    
    st.success(f"✅ Found SKU column: '{sku_column}'")
    
    # Create column mapping
    column_mapping = {}
    date_columns_found = []
    
    # First, map the SKU column
    column_mapping[sku_column] = "SKU"
    
    # Then map date columns
    for col_original in uploaded_plan.columns:
        if col_original == sku_column:
            continue  # Already mapped
            
        col_str = str(col_original)
        target_date = None
        
        # Try to parse as date
        try:
            # Handle different date formats
            if isinstance(col_original, (pd.Timestamp, date)):
                target_date = pd.to_datetime(col_original).strftime("%Y-%m-%d")
                date_columns_found.append(target_date)
            else:
                # Try parsing string as date
                parsed_date = pd.to_datetime(col_str, errors='coerce')
                if pd.notna(parsed_date):
                    target_date = parsed_date.strftime("%Y-%m-%d")
                    date_columns_found.append(target_date)
                else:
                    # Not a date, keep original name (cleaned)
                    target_date = re.sub(r'[^\w\s-]', '', col_str).strip()
            
            column_mapping[col_original] = target_date
            
        except Exception:
            # If date parsing fails, use cleaned column name
            target_date = re.sub(r'[^\w\s-]', '', col_str).strip()
            column_mapping[col_original] = target_date
    
    st.info(f"📅 Date columns found in Excel: {date_columns_found}")
    
    # Apply column renaming
    uploaded_plan_renamed = uploaded_plan.rename(columns=column_mapping)
    
    # Debug: Show what we have after renaming
    st.info(f"🔄 Columns after renaming: {list(uploaded_plan_renamed.columns)}")
    
    # Clean the SKU column data
    uploaded_plan_renamed["SKU"] = robust_string_clean(uploaded_plan_renamed["SKU"])
    
    # Process ALL columns that look like dates or are in our date_strings list
    for col in uploaded_plan_renamed.columns:
        if col == "SKU":
            continue
        
        # Convert to numeric, handling any text or empty values
        uploaded_plan_renamed[col] = pd.to_numeric(
            uploaded_plan_renamed[col], errors="coerce"
        ).fillna(0)
    
    # Debug: Show a sample of the data
    st.success(f"✅ Data preview after processing:")
    st.dataframe(uploaded_plan_renamed.head(), use_container_width=True)
    
    # Ensure all required date columns exist (from the app's date range)
    for date_str in date_strings:
        if date_str not in uploaded_plan_renamed.columns:
            uploaded_plan_renamed[date_str] = 0
            st.warning(f"⚠️ Date column '{date_str}' not found in Excel. Adding with zero values.")
    
    # Keep only SKU and date columns that are needed
    keep_cols = ["SKU"] + date_strings
    
    # Check which columns exist before trying to keep them
    existing_keep_cols = [col for col in keep_cols if col in uploaded_plan_renamed.columns]
    final_plan = uploaded_plan_renamed[existing_keep_cols].copy()
    
    # Add missing date columns with zeros
    for date_str in date_strings:
        if date_str not in final_plan.columns:
            final_plan[date_str] = 0
    
    # Reorder columns to match expected order
    final_plan = final_plan[["SKU"] + date_strings]
    
    # Remove rows where SKU is empty
    final_plan = final_plan[final_plan["SKU"].str.strip() != ""]
    
    # Final debug info
    st.success(f"✅ Final data structure: {len(final_plan)} rows, {len(final_plan.columns)} columns")
    st.success(f"📊 Final column order: {list(final_plan.columns)}")
    
    return final_plan

def main():
    st.set_page_config(layout="wide")
    st.title("SKU Production Planner & MRP Run")

    # Load SKU Data
    raw_materials_df = load_data()
    sku_list = raw_materials_df["SKU"].dropna().unique().tolist()
    st.success(f"SKU & Material data loaded from: {SKU_FILE_PATH}")

    # Dates setup
    if "num_extra_dates" not in st.session_state:
        st.session_state.num_extra_dates = 0
    num_extra_dates = st.number_input(
        "How many extra days to plan?",
        min_value=0, max_value=30,
        value=st.session_state.num_extra_dates,
        step=1
    )
    st.session_state.num_extra_dates = num_extra_dates
    dates_list = [date.today()] + [date.today() + timedelta(days=i) for i in range(1, num_extra_dates + 1)]
    date_strings = [d.strftime("%Y-%m-%d") for d in dates_list]

    # Choose Input Method
    st.subheader("Production Plan Input Method")
    plan_input_mode = st.radio(
        "How would you like to provide the production plan?",
        ["Define manually", "Upload from Excel"],
        horizontal=True,
        key="plan_input_mode_radio"
    )

    # Initialize separate session state variables for each mode
    if "manual_plan_df" not in st.session_state:
        st.session_state.manual_plan_df = pd.DataFrame()
    
    if "uploaded_plan_df" not in st.session_state:
        st.session_state.uploaded_plan_df = pd.DataFrame()
    
    # Track which mode was last used
    if "current_mode" not in st.session_state:
        st.session_state.current_mode = plan_input_mode
    
    # If mode changed, update the tracking
    if st.session_state.current_mode != plan_input_mode:
        st.session_state.current_mode = plan_input_mode

    # Manual Mode
    if plan_input_mode == "Define manually":
        st.info("📝 **Manual Definition Mode** - Create your production plan from scratch")
        
        if st.session_state.manual_plan_df.empty:
            rows = st.number_input("How many SKU rows?", min_value=1, max_value=50, value=5, step=1, key="manual_rows")
            if st.button("Initialize Manual Plan", type="secondary"):
                st.session_state.manual_plan_df = pd.DataFrame({"SKU": [""] * rows})
                for d in date_strings:
                    st.session_state.manual_plan_df[d] = 0
                st.rerun()
        else:
            cols_to_keep = ["SKU"] + date_strings
            st.session_state.manual_plan_df = st.session_state.manual_plan_df.reindex(columns=cols_to_keep, fill_value=0)
        
        # Set the active dataframe to manual
        if not st.session_state.manual_plan_df.empty:
            st.session_state.matrix_df = st.session_state.manual_plan_df.copy()

    # Upload Mode - FIXED VERSION
    elif plan_input_mode == "Upload from Excel":
        st.info("📁 **Excel Upload Mode** - Load production plan from Excel file")
        
        # Button to trigger Excel upload/reload
        col1, col2 = st.columns([1, 3])
        with col1:
            load_excel = st.button("📥 Load from Excel", type="secondary")
        with col2:
            if not st.session_state.uploaded_plan_df.empty:
                st.success(f"✅ Excel data loaded ({len(st.session_state.uploaded_plan_df)} rows)")
        
        # Load Excel data when button is clicked or if not loaded yet
        if load_excel or st.session_state.uploaded_plan_df.empty:
            try:
                uploaded_plan = pd.read_excel(PLAN_FILE_PATH, sheet_name="Sheet1")
                
                # Use improved processing function
                processed_plan = process_uploaded_plan(uploaded_plan, date_strings)
                
                if processed_plan is not None:
                    st.session_state.uploaded_plan_df = processed_plan
                    st.success(f"✅ Production plan loaded successfully from: {PLAN_FILE_PATH}")
                    st.success(f"📊 Loaded {len(st.session_state.uploaded_plan_df)} SKU rows with data")
                    
                    # Show preview of loaded data
                    with st.expander("Preview of loaded data"):
                        st.dataframe(st.session_state.uploaded_plan_df.head(), use_container_width=True)
                
            except FileNotFoundError:
                st.error(f"❌ No plan file found at {PLAN_FILE_PATH}")
                st.warning("Please ensure the Excel file exists at the specified path.")
            except Exception as e:
                st.error(f"❌ Error loading plan: {e}")
        
        # Set the active dataframe to uploaded
        if not st.session_state.uploaded_plan_df.empty:
            st.session_state.matrix_df = st.session_state.uploaded_plan_df.copy()

    # Editable Grid
    st.subheader(f"Production Plan (Editable) - {plan_input_mode}")
    if "matrix_df" not in st.session_state or st.session_state.matrix_df.empty:
        if plan_input_mode == "Define manually":
            st.warning("📝 Click 'Initialize Manual Plan' above to start creating your production plan manually.")
        else:
            st.warning("📁 Click 'Load from Excel' above to load your production plan from the Excel file.")
    else:
        # Ensure matrix_df matches current date_strings
        for d in date_strings:
            if d not in st.session_state.matrix_df.columns:
                st.session_state.matrix_df[d] = 0
        cols_to_keep = ["SKU"] + date_strings
        st.session_state.matrix_df = st.session_state.matrix_df.reindex(columns=cols_to_keep, fill_value=0)

        # Ensure all date columns are numeric
        for d in date_strings:
            st.session_state.matrix_df[d] = pd.to_numeric(
                st.session_state.matrix_df[d], errors="coerce"
            ).fillna(0).astype(int)

        # Add/Remove rows functionality (available for both modes)
        col1, col2, col3, col4 = st.columns([1, 1, 1, 3])
        
        with col1:
            if st.button("➕ Add Row"):
                new_row = pd.DataFrame({"SKU": [""]})
                for d in date_strings:
                    new_row[d] = 0
                
                if plan_input_mode == "Define manually":
                    st.session_state.manual_plan_df = pd.concat([st.session_state.manual_plan_df, new_row], ignore_index=True)
                    st.session_state.matrix_df = st.session_state.manual_plan_df.copy()
                else:
                    st.session_state.uploaded_plan_df = pd.concat([st.session_state.uploaded_plan_df, new_row], ignore_index=True)
                    st.session_state.matrix_df = st.session_state.uploaded_plan_df.copy()
                st.rerun()
        
        with col2:
            current_df = st.session_state.manual_plan_df if plan_input_mode == "Define manually" else st.session_state.uploaded_plan_df
            if st.button("➖ Remove Last Row") and len(current_df) > 1:
                if plan_input_mode == "Define manually":
                    st.session_state.manual_plan_df = st.session_state.manual_plan_df.iloc[:-1]
                    st.session_state.matrix_df = st.session_state.manual_plan_df.copy()
                else:
                    st.session_state.uploaded_plan_df = st.session_state.uploaded_plan_df.iloc[:-1]
                    st.session_state.matrix_df = st.session_state.uploaded_plan_df.copy()
                st.rerun()
        
        with col3:
            if plan_input_mode == "Upload from Excel":
                # Row deletion selector for Excel mode
                if len(st.session_state.uploaded_plan_df) > 1:
                    row_to_delete = st.selectbox(
                        "Delete row:",
                        options=list(range(len(st.session_state.uploaded_plan_df))),
                        format_func=lambda x: f"Row {x+1}: {st.session_state.uploaded_plan_df.iloc[x]['SKU'] if st.session_state.uploaded_plan_df.iloc[x]['SKU'] else 'Empty'}",
                        key="delete_row_selector"
                    )
                    if st.button("🗑️ Delete Selected"):
                        st.session_state.uploaded_plan_df = st.session_state.uploaded_plan_df.drop(index=row_to_delete).reset_index(drop=True)
                        st.session_state.matrix_df = st.session_state.uploaded_plan_df.copy()
                        st.success(f"Deleted row {row_to_delete + 1}")
                        st.rerun()
            else:
                # Row deletion selector for Manual mode
                if len(st.session_state.manual_plan_df) > 1:
                    row_to_delete = st.selectbox(
                        "Delete row:",
                        options=list(range(len(st.session_state.manual_plan_df))),
                        format_func=lambda x: f"Row {x+1}: {st.session_state.manual_plan_df.iloc[x]['SKU'] if st.session_state.manual_plan_df.iloc[x]['SKU'] else 'Empty'}",
                        key="delete_row_selector_manual"
                    )
                    if st.button("🗑️ Delete Selected"):
                        st.session_state.manual_plan_df = st.session_state.manual_plan_df.drop(index=row_to_delete).reset_index(drop=True)
                        st.session_state.matrix_df = st.session_state.manual_plan_df.copy()
                        st.success(f"Deleted row {row_to_delete + 1}")
                        st.rerun()
        
        # Info message for Excel mode
        if plan_input_mode == "Upload from Excel":
            st.info("💡 **Excel Mode**: You can add/remove rows and edit values. Use 'Load from Excel' to reload original data if needed.")

        # Dynamic Header Display
        header_cols = st.columns([3] + [1] * len(date_strings))
        header_cols[0].markdown("**SKU**")
        for i, d in enumerate(date_strings):
            header_cols[i + 1].markdown(f"**{d}**")

        num_rows = len(st.session_state.matrix_df)
        sku_options = [""] + sku_list
        
        for row in range(num_rows):
            row_cols = st.columns([3] + [1] * len(date_strings))
            
            # Get current SKU and find its index in options
            current_sku = str(st.session_state.matrix_df.iloc[row]["SKU"]).strip()
            
            # Find index in sku_options, default to 0 (empty) if not found
            try:
                sku_index = sku_options.index(current_sku) if current_sku in sku_options else 0
            except ValueError:
                sku_index = 0
            
            # SKU Dropdown
            selected_sku = row_cols[0].selectbox(
                label="SKU", 
                options=sku_options, 
                index=sku_index, 
                key=f"sku_{row}",
                label_visibility="collapsed"
            )
            # Save changes back to the appropriate session state
            if plan_input_mode == "Define manually":
                st.session_state.manual_plan_df.at[row, "SKU"] = selected_sku
            else:
                st.session_state.uploaded_plan_df.at[row, "SKU"] = selected_sku
            
            # Quantity Inputs
            for i, d in enumerate(date_strings):
                current_qty = int(st.session_state.matrix_df.iloc[row][d])
                qty_val = row_cols[i + 1].number_input(
                    label=d,
                    min_value=0, step=1,
                    value=current_qty,
                    key=f"qty_{row}_{d}",
                    format="%d",
                    label_visibility="collapsed"
                )
                # Save changes back to the appropriate session state
                if plan_input_mode == "Define manually":
                    st.session_state.manual_plan_df.at[row, d] = qty_val
                else:
                    st.session_state.uploaded_plan_df.at[row, d] = qty_val

        # Download Production Plan
        st.markdown("---")
        col_download1, col_download2, col_download3 = st.columns([1, 1, 2])
        
        with col_download1:
            # Prepare production plan for download
            download_df = st.session_state.matrix_df.copy()
            buffer_plan = io.BytesIO()
            download_df.to_excel(buffer_plan, index=False, sheet_name="ProductionPlan")
            buffer_plan.seek(0)
            
            st.download_button(
                label="📥 Download Production Plan",
                data=buffer_plan,
                file_name=f"ProductionPlan_{date.today().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
        
        with col_download2:
            st.metric("Total SKUs in Plan", len(download_df[download_df['SKU'] != '']))
        
        with col_download3:
            # Calculate total production quantity across all dates
            total_qty = 0
            for d in date_strings:
                if d in download_df.columns:
                    total_qty += download_df[d].sum()
            st.metric("Total Production Quantity", f"{int(total_qty):,}")

    # Run MRP
    if st.button("Run MRP", type="primary"):
        if "matrix_df" not in st.session_state or st.session_state.matrix_df.empty:
            st.warning("Please define or upload a production plan first.")
        else:
            with st.spinner("Performing MRP..."):
                mrp_result = perform_mrp_run(st.session_state.matrix_df, raw_materials_df, date_strings)
            st.session_state.mrp_result = mrp_result
            st.success("MRP run completed!")

    # Show Results
    if "mrp_result" in st.session_state and not st.session_state.mrp_result.empty:
        st.subheader("MRP Results: Remaining Raw Material Stock")

        # Search functionality
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            search_term = st.text_input(
                "🔍 Search for Material/Part Number:",
                placeholder="Enter material name or part number...",
                help="Search in Material name, Material Description, or Supplier Name"
            )
        
        with col2:
            sort_option = st.selectbox(
                "Sort by:",
                ["Negative Stock First", "Material Name (A-Z)", "Material Name (Z-A)", "Total Stock (Low to High)", "Total Stock (High to Low)"],
                help="Choose how to sort the results"
            )
        
        with col3:
            show_negative_only = st.checkbox(
                "Show Only Negative Stock",
                value=False,
                help="Display only materials with negative stock in any date"
            )
        
        # Create a copy of results for filtering/sorting
        display_df = st.session_state.mrp_result.copy()
        
        # Add Material name as a column (it's currently the index)
        display_df.insert(0, 'Material', display_df.index)
        
        # Apply search filter
        if search_term:
            search_term_upper = search_term.upper()
            mask = (
                display_df['Material'].str.upper().str.contains(search_term_upper, na=False) |
                display_df['Material Description'].str.upper().str.contains(search_term_upper, na=False) |
                display_df['Supplier Name'].str.upper().str.contains(search_term_upper, na=False)
            )
            display_df = display_df[mask]
            
            if len(display_df) == 0:
                st.warning(f"⚠️ No results found for '{search_term}'")
            else:
                st.success(f"✅ Found {len(display_df)} material(s) matching '{search_term}'")
        
        # Filter for negative stock only
        if show_negative_only:
            # Get date columns (exclude the info columns)
            date_cols = [col for col in display_df.columns if col not in ['Material', 'Material Description', 'Supplier Name', 'MRP', 'Total Stock']]
            
            # Check if any date column has negative values
            has_negative = display_df[date_cols].lt(0).any(axis=1)
            display_df = display_df[has_negative]
            
            if len(display_df) == 0:
                st.success("✅ Great! No materials have negative stock.")
            else:
                st.warning(f"⚠️ {len(display_df)} material(s) have negative stock on one or more dates")
        
        # Apply sorting
        if sort_option == "Negative Stock First":
            # Get date columns
            date_cols = [col for col in display_df.columns if col not in ['Material', 'Material Description', 'Supplier Name', 'MRP', 'Total Stock']]
            
            # Create a column for minimum stock across all dates
            display_df['_min_stock'] = display_df[date_cols].min(axis=1)
            
            # Sort by minimum stock (lowest first, which will show negatives at top)
            display_df = display_df.sort_values('_min_stock', ascending=True)
            
            # Drop the temporary column
            display_df = display_df.drop(columns=['_min_stock'])
            
        elif sort_option == "Material Name (A-Z)":
            display_df = display_df.sort_values('Material', ascending=True)
            
        elif sort_option == "Material Name (Z-A)":
            display_df = display_df.sort_values('Material', ascending=False)
            
        elif sort_option == "Total Stock (Low to High)":
            display_df = display_df.sort_values('Total Stock', ascending=True)
            
        elif sort_option == "Total Stock (High to Low)":
            display_df = display_df.sort_values('Total Stock', ascending=False)
        
        # Set Material back as index for display
        display_df = display_df.set_index('Material')
        
        # Show summary statistics
        date_cols = [col for col in display_df.columns if col not in ['Material Description', 'Supplier Name', 'MRP', 'Total Stock']]
        
        if len(date_cols) > 0:
            negative_materials = display_df[date_cols].lt(0).any(axis=1).sum()
            total_materials = len(display_df)
            
            col_stat1, col_stat2, col_stat3 = st.columns(3)
            with col_stat1:
                st.metric("Total Materials", total_materials)
            with col_stat2:
                st.metric("Materials with Negative Stock", negative_materials)
            with col_stat3:
                if negative_materials > 0:
                    st.metric("Materials OK", total_materials - negative_materials)
                else:
                    st.metric("✅ All Materials OK", total_materials)
        
        # Display the filtered/sorted results
        def highlight_negatives(val):
            try:
                if float(val) < 0:
                    return "background-color: #ffcccc"
                # Highlight if stock is exactly zero (optional visual cue)
                if float(val) == 0:
                    return "background-color: #ffffcc" 
            except Exception:
                pass
            return ""

        st.dataframe(
            display_df.style.applymap(highlight_negatives),
            use_container_width=True,
            height=600
        )

        buffer = io.BytesIO()
        display_df.to_excel(buffer, index=True)
        buffer.seek(0)
        st.download_button(
            label="📥 Download MRP Results as Excel",
            data=buffer,
            file_name=f"MRP_Results_{date.today().strftime('%Y%m%d')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # Clear Data - Updated to handle both modes
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("🗑️ Clear Manual Plan", type="secondary"):
            st.session_state.manual_plan_df = pd.DataFrame()
            if plan_input_mode == "Define manually":
                st.session_state.matrix_df = pd.DataFrame()
            st.success("Manual plan cleared.")
            st.rerun()
    
    with col2:
        if st.button("🗑️ Clear Excel Plan", type="secondary"):
            st.session_state.uploaded_plan_df = pd.DataFrame()
            if plan_input_mode == "Upload from Excel":
                st.session_state.matrix_df = pd.DataFrame()
            st.success("Excel plan cleared.")
            st.rerun()
    
    with col3:
        if st.button("🗑️ Clear All Data", type="secondary"):
            st.session_state.manual_plan_df = pd.DataFrame()
            st.session_state.uploaded_plan_df = pd.DataFrame()
            st.session_state.matrix_df = pd.DataFrame()
            if "mrp_result" in st.session_state:
                del st.session_state.mrp_result
            st.session_state.num_extra_dates = 0
            st.success("All data cleared.")
            st.rerun()

if __name__ == "__main__":
    main()
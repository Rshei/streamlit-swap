import streamlit as st
import pyrebase
import pandas as pd
from datetime import datetime, timedelta
import json
from google.cloud import firestore
from passlib.hash import pbkdf2_sha256
import os
from dotenv import load_dotenv

# Load environment variables from a .env file
load_dotenv()

# Load Firebase configuration from environment variable
firebase_config_path = os.getenv("FIREBASE_CONFIG")
with open(firebase_config_path) as f:
    firebase_config = json.load(f)

firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()

# Load Firestore key from environment variable
firestore_key_path = os.getenv("FIRESTORE_KEY")
db = firestore.Client.from_service_account_json(firestore_key_path)

# Your existing code...

def sign_up():
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    full_name = st.text_input("Full Name")
    if st.button("Sign Up"):
        try:
            auth.create_user_with_email_and_password(email, password)
            user = auth.sign_in_with_email_and_password(email, password)
            user_data = {
                "email": email,
                "full_name": full_name,
                "password_hash": pbkdf2_sha256.hash(password)  # Hash the password
            }
            db.collection('users').document(user['localId']).set(user_data)
            st.success("Successfully signed up!")
            return user
        except Exception as e:
            st.error(f"Sign-up failed: {e}")        

def login():
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    login_button = st.button("Login")

    if login_button:
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state['logged_in'] = True
            st.session_state['user'] = user
            st.success("Successfully logged in!")
        except Exception as e:
            if "EMAIL_NOT_FOUND" in str(e) or "INVALID_PASSWORD" in str(e):
                st.error("Wrong email or password.")
            else:
                st.error("Login failed: Please try again.")

def logout():
    st.session_state['logged_in'] = False
    st.session_state['user'] = None
    st.success("Successfully logged out!")

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['user'] = None

selected = None  # Initialize selected outside of the conditional blocks

if not st.session_state['logged_in']:
    action = st.selectbox("Choose action", ["Login", "Sign Up"])
    if action == "Login":
        login()
    else:
        user = sign_up()
        if user:
            st.session_state['logged_in'] = True
            st.session_state['user'] = user
else:
    user_email = st.session_state['user']['email']
    user_doc = db.collection('users').where("email", "==", user_email).get()
    if len(user_doc) == 1:
        user_data = user_doc[0].to_dict()
        user_full_name = user_data.get("full_name", "Unknown")
    else:
        user_full_name = "Unknown"
    st.sidebar.write(f"Logged in as: {user_full_name} ({user_email})")
    if st.sidebar.button("Logout"):
        logout()

    selected = st.sidebar.radio("Select action:", ["Insert Shifts", "Find Swap", "Shifts for swap", "Delete Shift"])     
     

def generate_dates(year, month):
    start_date = datetime(year, month, 1)
    if month == 12:
        num_days = (datetime(year + 1, 1, 1) - start_date).days
    else:
        num_days = (datetime(year, month + 1, 1) - start_date).days
    dates_list = [start_date + timedelta(days=i) for i in range(num_days)]
    return [date.strftime('%Y-%m-%d') for date in dates_list]

def find_matches(df):
    matches = []
    for i in range(len(df)):
        for j in range(i + 1, len(df)):
            shift_employee1 = df.iloc[i]
            shift_employee2 = df.iloc[j]
            if shift_employee1['date'] == shift_employee2['date']:
                if shift_employee1['employee_name'] != shift_employee2['employee_name']:
                    if shift_employee1['give_away'] in shift_employee2[['can_take_early', 'can_take_morning', 'can_take_evening', 'can_take_night', 'can_take_rest']].values:
                        if shift_employee2['give_away'] in shift_employee1[['can_take_early', 'can_take_morning', 'can_take_evening', 'can_take_night', 'can_take_rest']].values:
                            matches.append((shift_employee1['employee_name'], shift_employee2['employee_name'], shift_employee1['date'], shift_employee1['give_away'], shift_employee2['give_away']))
    return matches

def save_shifts_to_firestore(df):
    for index, row in df.iterrows():
        doc_id = f"{row['employee_name']}_{row['date']}"
        db.collection('shifts').document(doc_id).set(row.to_dict())

def fetch_shifts_from_firestore():
    shifts_ref = db.collection('shifts')
    return pd.DataFrame([doc.to_dict() for doc in shifts_ref.stream()])

def update_shift_in_firestore(old_doc_id, new_data):
    db.collection('shifts').document(old_doc_id).delete()
    new_doc_id = f"{new_data['employee_name']}_{new_data['date']}"
    db.collection('shifts').document(new_doc_id).set(new_data)

def delete_shift_from_firestore(doc_id):
    db.collection('shifts').document(doc_id).delete()

if selected == "Insert Shifts":
    selected_month = st.selectbox("Select the month:", options=range(1, 13))
    st.write("Shift Swap Submission Form")
    df = pd.DataFrame(columns=['date', 'employee_name', 'give_away', 'can_take_early', 'can_take_morning', 'can_take_evening', 'can_take_night', 'can_take_rest'])
    shifts = ['early', 'morning', 'evening', 'night', 'rest', None]
    config = {
        'date': st.column_config.SelectboxColumn('date', width='small', options=generate_dates(2024, selected_month)),
        'employee_name': st.column_config.SelectboxColumn('Employee name', options=[user_full_name]),
        'give_away': st.column_config.SelectboxColumn('Give Away', options=shifts),
        'can_take_early': st.column_config.SelectboxColumn('Can Take Early', options=['early', None]),
        'can_take_morning': st.column_config.SelectboxColumn('Can Take Morning', options=['morning', None]),
        'can_take_evening': st.column_config.SelectboxColumn('Can Take Evening', options=['evening', None]),
        'can_take_night': st.column_config.SelectboxColumn('Can Take Night', options=['night', None]),
        'can_take_rest': st.column_config.SelectboxColumn('Can Take Rest', options=['rest', None])
    }

    result = st.data_editor(df, column_config=config, num_rows='dynamic', hide_index=True)
    
    if st.button("Submit"):
        save_shifts_to_firestore(result)
        st.write("Data submitted!")
        
    matches = find_matches(result)

elif selected == "Find Swap":
    employee_name = user_full_name
    df = fetch_shifts_from_firestore()
    matches = find_matches(df)
    if matches:
        st.write("Shift swapping matches for", employee_name + ":")
        for match in matches:
            if match[0] == employee_name or match[1] == employee_name:
                st.write(f"{match[0]} and {match[1]} on {match[2]} can swap shifts.")
                st.write(f"{match[0]} gives away {match[3]} and {match[1]} gives away {match[4]}")
    else:
        st.write("No matches found for", employee_name)

elif selected == "Shifts for swap":
    df = fetch_shifts_from_firestore()

    # Reorder columns
    df = df[['employee_name', 'date', 'give_away', 'can_take_early', 'can_take_morning', 'can_take_evening', 'can_take_night', 'can_take_rest']]
    
    # Display all shifts in a table
    st.write("All Assigned Shifts:")
    st.dataframe(df)

elif selected == "Delete Shift":
    employee_name = user_full_name
    df = fetch_shifts_from_firestore()
    # Reorder columns
    df = df[['date', 'employee_name', 'give_away', 'can_take_early', 'can_take_morning', 'can_take_evening', 'can_take_night', 'can_take_rest']]
    
    user_shifts = df[df['employee_name'] == employee_name]
    
    if not user_shifts.empty:
        st.write(f"Delete Shifts for {employee_name}:")
        st.dataframe(user_shifts)  # Display user's shifts in a dataframe
        
        # Create a dropdown to select the shift to delete
        shift_to_delete = st.selectbox("Select the shift to delete:", user_shifts['date'])
        
        # Find the corresponding row in the dataframe
        row_to_delete = user_shifts[user_shifts['date'] == shift_to_delete].iloc[0]
        
        # Create a unique key for the delete button
        delete_button_key = f"delete_{row_to_delete['date']}"
        
        # Display the selected shift and the delete button
        st.write(f"Shift on {row_to_delete['date']}: {row_to_delete['give_away']}")
        if st.button(f"Delete {shift_to_delete}", key=delete_button_key):
            delete_shift_from_firestore(f"{row_to_delete['employee_name']}_{row_to_delete['date']}")
            st.write("Shift deleted.")
    else:
        st.write(f"No shifts found for {employee_name}.")

import streamlit as st
import pyrebase
import pandas as pd
from datetime import datetime, timedelta
import json
from google.cloud import firestore
from passlib.hash import pbkdf2_sha256
import os
from dotenv import load_dotenv
import pdfplumber
from icalendar import Calendar, Event
import PyPDF2


# Firebase configuration
firebase_config = {
    "apiKey": st.secrets["firebase"]["apiKey"],
    "authDomain": st.secrets["firebase"]["authDomain"],
    "databaseURL": st.secrets["firebase"]["databaseURL"],
    "projectId": st.secrets["firebase"]["projectId"],
    "storageBucket": st.secrets["firebase"]["storageBucket"],
    "messagingSenderId": st.secrets["firebase"]["messagingSenderId"],
    "appId": st.secrets["firebase"]["appId"],
}

firebase = pyrebase.initialize_app(firebase_config)
auth = firebase.auth()

# Firestore configuration
firestore_config = {
    "type": st.secrets["firestore"]["type"],
    "project_id": st.secrets["firestore"]["project_id"],
    "private_key_id": st.secrets["firestore"]["private_key_id"],
    "private_key": st.secrets["firestore"]["private_key"],
    "client_email": st.secrets["firestore"]["client_email"],
    "client_id": st.secrets["firestore"]["client_id"],
    "auth_uri": st.secrets["firestore"]["auth_uri"],
    "token_uri": st.secrets["firestore"]["token_uri"],
    "auth_provider_x509_cert_url": st.secrets["firestore"]["auth_provider_x509_cert_url"],
    "client_x509_cert_url": st.secrets["firestore"]["client_x509_cert_url"]
}

db = firestore.Client.from_service_account_info(firestore_config)

# Define functions for authentication and Firestore operations

def sign_up():
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    full_name = st.text_input("Full Name")
    if st.button("Sign Up"):
        if not email or not password or not full_name:
            st.error("Please fill in all fields.")
        else:
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
                st.success("Press again on Sign Up")
                return user
            except Exception as e:
                st.error(f"Sign-up failed: {e}")        

def login():
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        try:
            user = auth.sign_in_with_email_and_password(email, password)
            st.session_state['logged_in'] = True
            st.session_state['user'] = user
            st.success("Successfully logged in!")
            st.success("Press again on Login!")
        except Exception as e:
            if "EMAIL_NOT_FOUND" in str(e) or "INVALID_PASSWORD" in str(e):
                st.error("Wrong email or password.")
            else:
                st.error("Login failed: Please try again.")

def logout():
    st.session_state['logged_in'] = False
    st.session_state['user'] = None
    st.success("Successfully logged out!")

# Initialize session state
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['user'] = None

selected = None  # Initialize selected outside of the conditional blocks

# Handle user authentication
if not st.session_state['logged_in']:
    action = st.radio("Choose action", ["Login", "Sign Up"])
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

    # Simplified mobile-friendly navigation
    selected = st.sidebar.radio("Select action:", ["Insert Shifts", "Matches", "Shifts for swap", "Delete Shift", "shifts to calendar"])         

# Function definitions for shift operations

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

def extract_shifts_from_pdf(pdf_file):
    # Read the PDF file
    reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page_num in range(len(reader.pages)):
        text += reader.pages[page_num].extract_text()
    
    # Extract shifts
    shifts = []
    lines = text.split('\n')
    for line in lines:
        if line.strip() and line[0].isdigit():
            parts = line.split()
            date = parts[0]
            shift = " ".join(parts[1:])
            shifts.append((date, shift))
    return shifts

def create_shift_event(date, shift):
    if shift == 'Rest' or shift == 'COMP0':
        return None, None
    start_time, end_time = shift.split(' - ')
    start_datetime = datetime.strptime(f"{date} {start_time}", "%Y-%m-%d %H:%M")
    end_datetime = datetime.strptime(f"{date} {end_time}", "%Y-%m-%d %H:%M")
    return start_datetime, end_datetime

def create_ics(events):
    cal = Calendar()
    cal.add('prodid', '-//My App//Shift Calendar//EN')
    cal.add('version', '2.0')

    for event in events:
        ical_event = Event()
        ical_event.add('summary', event['summary'])
        ical_event.add('dtstart', event['dtstart'])
        ical_event.add('dtend', event['dtend'])
        ical_event.add('dtstamp', datetime.utcnow())
        ical_event.add('uid', f"{event['dtstart'].strftime('%Y%m%dT%H%M%SZ')}-{event['summary']}@myapp.com")
        ical_event.add('description', 'Work shift')
        cal.add_component(ical_event)

    return cal.to_ical()
# Handle shift-related actions
if selected == "Insert Shifts":
    selected_month = st.selectbox("Select the month:", options=range(1, 13))
    st.write("Shift Swap Submission Form")
    df = pd.DataFrame(columns=['date', 'employee_name', 'give_away', 'can_take_early', 'can_take_morning', 'can_take_evening', 'can_take_night', 'can_take_rest'])
    shifts = ['early', 'morning', 'evening', 'night', 'rest', None]

    date = st.selectbox('Date', options=generate_dates(2024, selected_month))
    give_away = st.selectbox('Give Away', options=shifts)
    can_take_early = st.selectbox('Can Take Early', options=[None, 'early'])
    can_take_morning = st.selectbox('Can Take Morning', options=[None, 'morning'])
    can_take_evening = st.selectbox('Can Take Evening', options=[None, 'evening'])
    can_take_night = st.selectbox('Can Take Night', options=[None,'night'])
    can_take_rest = st.selectbox('Can Take Rest', options=[None,'rest'])

    if st.button("Submit"):
        new_row = {
            'date': date,
            'employee_name': user_full_name,
            'give_away': give_away,
            'can_take_early': can_take_early,
            'can_take_morning': can_take_morning,
            'can_take_evening': can_take_evening,
            'can_take_night': can_take_night,
            'can_take_rest': can_take_rest
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
        save_shifts_to_firestore(df)
        st.write("Data submitted!")

    matches = find_matches(df)

elif selected == "Matches":
    employee_name = user_full_name
    df = fetch_shifts_from_firestore()
    matches = find_matches(df)
    if matches:
        st.write(f"Matches for {employee_name}:")
        for match in matches:
            if match[0] == employee_name or match[1] == employee_name:
                match_with = match[1] if match[0] == employee_name else match[0]
                st.write(f"On {match[2]}, you have a match with {match_with}")
                st.write(f"{match_with} wants to give away {match[4]} for your {match[3]}.")
    else:
        st.write(f"No matches found for {employee_name}.")


elif selected == "Shifts for swap":
    df = fetch_shifts_from_firestore()
    df = df[['employee_name', 'date', 'give_away', 'can_take_early', 'can_take_morning', 'can_take_evening', 'can_take_night', 'can_take_rest']]
    st.write("All Assigned Shifts:")
    st.dataframe(df)

elif selected == "Delete Shift":
    employee_name = user_full_name
    df = fetch_shifts_from_firestore()
    df = df[['date', 'employee_name', 'give_away', 'can_take_early', 'can_take_morning', 'can_take_evening', 'can_take_night', 'can_take_rest']]
    user_shifts = df[df['employee_name'] == employee_name]
    
    if not user_shifts.empty:
        st.write(f"Delete Shifts for {employee_name}:")
        st.dataframe(user_shifts)
        shift_to_delete = st.selectbox("Select the shift to delete:", user_shifts['date'])
        row_to_delete = user_shifts[user_shifts['date'] == shift_to_delete].iloc[0]
        st.write(f"Shift on {row_to_delete['date']}: {row_to_delete['give_away']}")
        if st.button(f"Delete {shift_to_delete}"):
            delete_shift_from_firestore(f"{row_to_delete['employee_name']}_{row_to_delete['date']}")
            st.write("Shift deleted.")
    else:
        st.write(f"No shifts found for {employee_name}.")

elif selected == "shifts to calendar":
    uploaded_file = st.file_uploader("Upload your PDF file", type="pdf")

    if uploaded_file is not None:
        shifts = extract_shifts_from_pdf(uploaded_file)
        st.write("Extracted Shifts:", shifts)  # Debug statement
    
        # Process shifts
        events = []
        for shift_date, shift_time in shifts:
            start, end = create_shift_event(shift_date, shift_time)
            if start and end:
                events.append({
                    'summary': 'Work Shift',
                    'dtstart': start,
                    'dtend': end
                })
        
        st.write("Processed Events:", events)  # Debug statement
    
        # Create .ics content
        ics_content = create_ics(events)
        st.write("Generated ICS Content:", ics_content.decode('utf-8'))  # Debug statement
        
        # Provide .ics file for download
        st.download_button(label="Download ICS file", data=ics_content, file_name="shifts.ics", mime="text/calendar")

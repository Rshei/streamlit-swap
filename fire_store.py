from google.cloud import firestore

# Add a new user to the database
db = firestore.Client()
doc_ref = db.collection('users').document('alovelace')
doc_ref.set({
    'first': 'Ada',
    'last': 'Lovelace',
    'born': 1815
})

# Then query to list all users
users_ref = db.collection('users')

for doc in users_ref.stream():
    print('{} => {}'.format(doc.id, doc.to_dict()))
from database import get_database

db = get_database()
print(db.list_collection_names())  # this prints all collections in your MongoDB Atlas database

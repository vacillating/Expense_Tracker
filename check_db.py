from database import DBManager

db = DBManager()
df = db.get_transactions()
print("Total rows:", len(df))
print(df)

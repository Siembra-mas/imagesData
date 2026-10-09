import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/")
MONGO_DB = os.getenv("MONGO_DB", "dataset_auth")

mongo_client = MongoClient(MONGO_URI)
db = mongo_client[MONGO_DB]
users_col = db["users"]
users_col.create_index("username", unique=True)
users_col.update_many(
	{"role": {"$exists": False}},
	{"$set": {"role": "uploader"}},
)

dataset_catalog_col = db["dataset_catalog"]
uploads_col = db["uploads"]
dataset_catalog_col.create_index("dataset_type", unique=True)
uploads_col.create_index("upload_id", unique=True)
uploads_col.create_index("client_upload_id", unique=True, sparse=True)
uploads_col.create_index([("username", 1), ("created_at", -1)])

# Seed idempotente: los administradores pueden editar estos documentos directamente en MongoDB.
dataset_catalog_col.update_one(
	{"dataset_type": "cultivo"},
	{
		"$setOnInsert": {
			"dataset_type": "cultivo",
			"name": "Cultivo",
			"subtypes": ["caña", "maíz"],
			"is_active": True,
		}
	},
	upsert=True,
)
dataset_catalog_col.update_one(
	{"dataset_type": "radiografias"},
	{
		"$setOnInsert": {
			"dataset_type": "radiografias",
			"name": "Radiografías",
			"subtypes": [],
			"is_active": True,
		}
	},
	upsert=True,
)
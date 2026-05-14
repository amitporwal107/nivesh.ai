// mongo-init.js — runs once when MongoDB container is first created.
// Creates the app database and a dedicated app user.
// Root credentials come from MONGO_INITDB_ROOT_* env vars.

db = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE || 'nivesh_prod');

db.createUser({
  user: 'nivesh',
  pwd:  'Niv3shApp2026!',
  roles: [{ role: 'readWrite', db: db.getName() }],
});

db.createCollection('_init');
print('MongoDB init complete: database=' + db.getName());

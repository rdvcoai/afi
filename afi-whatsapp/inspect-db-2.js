const Database = require('better-sqlite3');
const db = new Database('account_latest.sqlite');
console.log("Files:", db.prepare("SELECT * FROM files").all());

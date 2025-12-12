const Database = require('better-sqlite3');
const db = new Database('account_latest.sqlite');
console.log(db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all());

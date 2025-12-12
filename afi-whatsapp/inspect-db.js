const Database = require('better-sqlite3');
const db = new Database('account_new.sqlite');

try {
    console.log("Tables:", db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all());
    console.log("Users:", db.prepare("SELECT * FROM users").all());
    console.log("Files:", db.prepare("SELECT * FROM files").all());
} catch (e) {
    console.error(e);
}

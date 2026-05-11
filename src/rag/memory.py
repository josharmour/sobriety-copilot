import sqlite3
import json
from dataclasses import dataclass, asdict
from typing import Optional, List

@dataclass
class UserState:
    user_id: str
    sobriety_date: Optional[str] = None
    current_step: int = 1
    notes: str = ""
    last_interaction: Optional[str] = None

class UserMemoryManager:
    def __init__(self, db_path: str = "user_memory.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS user_state (user_id TEXT PRIMARY KEY, sobriety_date TEXT, current_step INTEGER, notes TEXT, last_interaction TEXT)")

    def get_user_state(self, user_id: str) -> UserState:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute('SELECT * FROM user_state WHERE user_id = ?', (user_id,)).fetchone()
            if row:
                return UserState(*row)
            return UserState(user_id=user_id)

    def update_user_state(self, state: UserState):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('INSERT OR REPLACE INTO user_state (user_id, sobriety_date, current_step, notes, last_interaction) VALUES (?, ?, ?, ?, ?)', 
                         (state.user_id, state.sobriety_date, state.current_step, state.notes, state.last_interaction))

    def save_interaction(self, user_id: str, message: str, response: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS interaction_history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, message TEXT, response TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
            conn.execute('INSERT INTO interaction_history (user_id, message, response) VALUES (?, ?, ?)', (user_id, message, response))

    def get_recent_history(self, user_id: str, limit: int = 5) -> List[dict]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT message, response FROM interaction_history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?', (user_id, limit))
            return [{"message": row[0], "response": row[1]} for row in cursor.fetchall()]

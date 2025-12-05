# reminder_original.py
import threading, time
from datetime import datetime

# 全域清單
TASK_LIST = []

def check_time_for_task(task):
    """
    範例提醒函式：每 10 秒檢查一次，若到時間則印提醒。
    你可以把這裡改成要叫系統發送 Email、或其它動作。
    """
    title = task.get("title","提醒")
    target = task.get("target_time")
    snooze = task.get("snooze_minutes", 10)
    completed = task.get("completed", False)
    while True:
        now = datetime.now()
        if now >= target and not task.get("completed", False):
            print(f"[Reminder] {title} at {now.strftime('%Y-%m-%d %H:%M:%S')}")
            # 標記已執行
            task["completed"] = True
            break
        time.sleep(10)

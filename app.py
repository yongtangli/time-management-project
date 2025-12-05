# app.py
from flask import Flask, render_template, request, jsonify, send_file
import csv, os, threading, time
import pandas as pd
from datetime import datetime, timedelta

# 匯入 optimizer（請確保 optimizer.py 在同一資料夾）
try:
    from optimizer import optimize_minutes, make_blocks, optimize_blocks
except Exception as e:
    raise RuntimeError("缺少 optimizer.py 或載入失敗: " + str(e))

# 轉換器，把課表 CSV 轉成 optimizer.py 要的格式
def courses_csv_to_optimizer_df(path="courses.csv"):
    if not os.path.exists(path):
        return pd.DataFrame(columns=["course_name","credits","difficulty","category","exam_date"])
    df = pd.read_csv(path, encoding="utf-8")
    # 預期的欄位： day, period, course_name, credit, type, sweet, cool
    # 要把資料聚合成每門課一列：
    grp = {}
    for _, r in df.iterrows():
        name = str(r.get("course_name","")).strip()
        if not name:
            continue
        if name not in grp:
            grp[name] = {"course_name": name, "credits": float(r.get("credit",1) or 1),
                         "difficulty": float(((11 - float(r.get("sweet",5))) + float(r.get("cool",5))) / 2),
                         "category": r.get("type","選修"),
                         "exam_date": ""}
    out = pd.DataFrame(list(grp.values()))
    return out

# reminder 原始檔（在同資料夾）
try:
    import reminder_original as reminder
except Exception:
    # 若沒有 reminder_original.py，也建立一個簡單替代物以免 crash
    class Dummy:
        TASK_LIST = []
        def check_time_for_task(task):
            print("Reminder triggered:", task)
    reminder = Dummy

app = Flask(__name__, static_folder="static", template_folder="templates")

COURSES_CSV = "courses.csv"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/save_courses", methods=["POST"])
def api_save_courses():
    """
    接收前端發來的課表（JSON），儲存為 courses.csv
    期待資料格式： [{day, period, course_name, credit, type, sweet, cool}, ...]
    """
    data = request.get_json(force=True)
    # 寫 csv
    with open(COURSES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["day","period","course_name","credit","type","sweet","cool"])
        for row in data:
            writer.writerow([row.get("day",""), row.get("period",""), row.get("course_name",""),
                             row.get("credit",""), row.get("type",""), row.get("sweet",""), row.get("cool","")])
    return jsonify({"status":"ok"})

@app.route("/api/load_courses", methods=["GET"])
def api_load_courses():
    if not os.path.exists(COURSES_CSV):
        return jsonify([])
    df = pd.read_csv(COURSES_CSV, encoding="utf-8")
    return df.to_json(orient="records", force_ascii=False)

@app.route("/api/optimize_minutes", methods=["POST"])
def api_optimize_minutes():
    """
    由前端傳 total_minutes, min_minutes, round_to
    回傳 optimize_minutes 的結果
    """
    payload = request.get_json(force=True)
    total = int(payload.get("total_minutes", 180))
    min_minutes = int(payload.get("min_minutes", 0))
    round_to = int(payload.get("round_to", 30))
    df = courses_csv_to_optimizer_df(COURSES_CSV)
    if df.empty:
        return jsonify({"error":"無課程資料"}), 400
    out = optimize_minutes(df, total_minutes_today=total, min_minutes_per_course=min_minutes, round_to=round_to)
    # 返回 JSON（分鐘、權重、score）
    return out.reset_index().rename(columns={"index":"course_name"}).to_json(orient="records", force_ascii=False)

@app.route("/api/optimize_blocks", methods=["POST"])
def api_optimize_blocks():
    """
    前端傳 start_time, end_time (HH:MM)，server 生成 blocks，呼叫 optimize_blocks，回傳排程
    """
    payload = request.get_json(force=True)
    start = payload.get("start_time")
    end = payload.get("end_time")
    if not start or not end:
        return jsonify({"error":"請提供 start_time 與 end_time"}), 400
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    today = datetime.now().date()
    start_dt = datetime.combine(today, datetime.strptime(start,"%H:%M").time())
    end_dt = datetime.combine(today, datetime.strptime(end,"%H:%M").time())
    if end_dt <= start_dt:
        return jsonify({"error":"結束時間必須晚於開始"}), 400
    blocks = make_blocks(start_dt, end_dt, block_minutes=30)
    df = courses_csv_to_optimizer_df(COURSES_CSV)
    assign = optimize_blocks(df, blocks=blocks)
    # assign has block_time, course_name
    # 將 block_time 轉成字串
    assign['start'] = assign['block_time'].dt.strftime("%H:%M")
    assign['end'] = (assign['block_time'] + pd.Timedelta(minutes=30)).dt.strftime("%H:%M")
    return assign[['start','end','course_name']].to_json(orient="records", force_ascii=False)

# 啟動提醒背景工作（把排程丟給 reminder_original.py 的 TASK_LIST）
def start_reminder_background(schedule_records):
    """
    schedule_records: list of {start: "HH:MM", course_name: "..."}
    這個 function 會填 reminder.TASK_LIST，並啟動背景執行緒
    """
    # 清空原本的清單
    if hasattr(reminder, "TASK_LIST"):
        reminder.TASK_LIST.clear()
    else:
        reminder.TASK_LIST = []
    now = datetime.now()
    for r in schedule_records:
        time_str = r.get("start")
        try:
            h,m = map(int, time_str.split(":"))
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            reminder.TASK_LIST.append({
                "title": f"讀書：{r.get('course_name')}",
                "target_time": target,
                "snooze_minutes": 10,
                "completed": False
            })
        except Exception:
            continue
    # 啟動每個任務的背景檢查（使用 reminder.check_time_for_task）
    if hasattr(reminder, "check_time_for_task"):
        for task in reminder.TASK_LIST:
            t = threading.Thread(target=reminder.check_time_for_task, args=(task,))
            t.daemon = True
            t.start()

@app.route("/api/start_reminders", methods=["POST"])
def api_start_reminders():
    data = request.get_json(force=True)
    # data 預期為 [{start, end, course_name}, ...]
    start_reminder_background(data)
    return jsonify({"status":"reminders_started"})

# 下載 courses.csv
@app.route("/download/courses.csv")
def download_courses():
    if os.path.exists(COURSES_CSV):
        return send_file(COURSES_CSV, as_attachment=True)
    else:
        return jsonify({"error":"no file"}), 404

# 下載 schedule CSV（由前端或 server 產生）
@app.route("/download/schedule.csv")
def download_schedule():
    path = "study_schedule.csv"
    if os.path.exists(path):
        return send_file(path, as_attachment=True)
    return jsonify({"error":"no schedule"}), 404

if __name__ == "__main__":
    # 在本機執行時
    app.run(host="0.0.0.0", port=5000, debug=True)

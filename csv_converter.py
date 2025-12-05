# csv_converter.py
import pandas as pd
import os

def convert(csv_path="courses.csv"):
    if not os.path.exists(csv_path):
        return pd.DataFrame(columns=["course_name","credits","difficulty","category","exam_date"])
    df = pd.read_csv(csv_path, encoding="utf-8")
    grp = {}
    for _, r in df.iterrows():
        name = str(r.get("course_name","")).strip()
        if not name: continue
        if name not in grp:
            grp[name] = {
                "course_name": name,
                "credits": float(r.get("credit",1) or 1),
                "difficulty": float(((11 - float(r.get("sweet",5))) + float(r.get("cool",5))) / 2),
                "category": r.get("type","選修"),
                "exam_date": ""
            }
    return pd.DataFrame(list(grp.values()))

if __name__ == "__main__":
    print(convert("courses.csv"))

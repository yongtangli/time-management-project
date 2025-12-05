// static/script.js
// 建表
const days = ["1","2","3","4","5"];
const periods = Array.from({length:10},(_,i)=>i+1);
const tbody = document.getElementById("schedule-body");
for(let p of periods){
  const tr = document.createElement("tr");
  const th = document.createElement("th"); th.textContent = `第 ${p} 節`; tr.appendChild(th);
  for(let d of days){
    const td = document.createElement("td");
    td.classList.add("cell");
    td.dataset.day = d; td.dataset.period = p;
    td.addEventListener("mousedown", onMouseDown);
    td.addEventListener("mouseover", onMouseOver);
    td.addEventListener("mouseup", onMouseUp);
    tr.appendChild(td);
  }
  tbody.appendChild(tr);
}

// 狀態
let isMouseDown=false, selection=new Set();
let courses=[]; // {name,credit,type,sweet,cool,cells:[]}
function onMouseDown(e){ isMouseDown=true; toggleSelect(e.currentTarget); }
function onMouseOver(e){ if(isMouseDown) toggleSelect(e.currentTarget); }
function onMouseUp(e){ isMouseDown=false; if(selection.size>0) openCoursePrompt(); }
document.addEventListener("mouseup", ()=> isMouseDown=false);

function toggleSelect(cell){
  const k = `${cell.dataset.day}-${cell.dataset.period}`;
  if(selection.has(k)){ selection.delete(k); cell.classList.remove("selected"); }
  else { selection.add(k); cell.classList.add("selected"); }
}

function openCoursePrompt(){
  const name = prompt("課名：");
  if(!name){ clearSelection(); return; }
  const credit = prompt("學分（數字）：", "2") || "1";
  const type = prompt("類別（必修/選修/通識/其他）：", "必修") || "必修";
  const sweet = prompt("甜度 (1~10)：", "5") || "5";
  const cool = prompt("涼度 (1~10)：", "5") || "5";

  // check conflicts
  const conflicts = [];
  for(const k of selection){
    const [d,p] = k.split("-");
    const cell = document.querySelector(`td[data-day='${d}'][data-period='${p}']`);
    if(cell && cell.dataset.courseName && cell.dataset.courseName !== name){
      conflicts.push(k);
    }
  }
  if(conflicts.length>0){
    if(!confirm("偵測到衝堂，按確定覆蓋、取消放棄")){ clearSelection(); return; }
    // else we will overwrite
  }

  // assign
  let course = courses.find(c=>c.name===name);
  if(!course){ course = {name,credit,type,sweet,cool,cells:[]}; courses.push(course); }
  for(const k of selection){
    const [d,p] = k.split("-");
    const cell = document.querySelector(`td[data-day='${d}'][data-period='${p}']`);
    if(cell){
      cell.textContent = name;
      cell.dataset.courseName = name;
      cell.classList.add("occupied");
      course.cells.push(k);
    }
  }
  // dedupe
  course.cells = Array.from(new Set(course.cells));
  renderCourseList();
  clearSelection();
}

function clearSelection(){
  for(const k of selection){
    const [d,p]=k.split("-"); const cell = document.querySelector(`td[data-day='${d}'][data-period='${p}']`);
    if(cell) cell.classList.remove("selected");
  }
  selection.clear();
}

function renderCourseList(){
  const tb = document.querySelector("#courseList tbody"); tb.innerHTML="";
  for(const c of courses){
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${c.name}</td><td>${c.credit}</td><td>${c.type}</td><td>${c.sweet}</td><td>${c.cool}</td><td>${c.cells.join(", ")}</td>`;
    tb.appendChild(tr);
  }
  detectConflicts();
}

function detectConflicts(){
  // map key->list of course names occupying it
  const map = {};
  courses.forEach(c => c.cells.forEach(k => { map[k]=map[k]||[]; map[k].push(c.name); }));
  document.querySelectorAll(".cell").forEach(cell=>cell.classList.remove("conflict"));
  for(const k in map){
    if(map[k].length>1){
      const [d,p]=k.split("-"); const cell = document.querySelector(`td[data-day='${d}'][data-period='${p}']`);
      if(cell) cell.classList.add("conflict");
    }
  }
}

// 清除整個表格
document.getElementById("btnClear").addEventListener("click", ()=>{
  if(!confirm("確定清除整個課表？")) return;
  courses=[]; document.querySelectorAll(".cell").forEach(c=>{ c.textContent=""; c.classList.remove("occupied","conflict"); delete c.dataset.courseName; });
  renderCourseList();
});

// 儲存到伺服器
document.getElementById("btnSaveServer").addEventListener("click", async ()=>{
  // build rows
  const rows = [];
  courses.forEach(c=>{
    c.cells.forEach(k=>{
      const [d,p]=k.split("-"); rows.push({day:d,period:p,course_name:c.name,credit:c.credit,type:c.type,sweet:c.sweet,cool:c.cool});
    });
  });
  // send
  const res = await fetch("/api/save_courses", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(rows)});
  const j = await res.json();
  if(j.status==="ok") alert("已儲存到伺服器 courses.csv");
});

// 下載排程（server 端）
document.getElementById("btnDownloadSchedule").addEventListener("click", ()=> {
  window.location.href = "/download/schedule.csv";
});

// 計算分鐘（server）
document.getElementById("btnCalcMinutes").addEventListener("click", async ()=>{
  const total = Number(document.getElementById("totalMinutes").value||0);
  const minm = Number(document.getElementById("minMinutes").value||0);
  const roundto = Number(document.getElementById("roundTo").value||30);
  const res = await fetch("/api/optimize_minutes", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({total_minutes:total, min_minutes:minm, round_to:roundto})});
  if(!res.ok){ alert("計算失敗"); return; }
  const arr = await res.json();
  const panel = document.getElementById("minutesResult"); panel.innerHTML = "<h4>分鐘分配</h4>";
  const tbl = document.createElement("table"); tbl.style.width="100%"; tbl.innerHTML="<tr><th>課名</th><th>minutes</th><th>weight</th></tr>";
  JSON.parse(arr).forEach(r=>{ const tr=document.createElement("tr"); tr.innerHTML=`<td>${r.course_name}</td><td>${r.minutes}</td><td>${r.weight}</td>`; tbl.appendChild(tr); });
  panel.appendChild(tbl);
});

// 生成 blocks（server）
document.getElementById("btnMakeBlocks").addEventListener("click", async ()=>{
  const start = document.getElementById("startTime").value;
  const end = document.getElementById("endTime").value;
  if(!start||!end){ alert("請選時間"); return; }
  const res = await fetch("/api/optimize_blocks", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({start_time:start,end_time:end})});
  if(!res.ok){ alert("生成失敗"); return; }
  const arr = JSON.parse(await res.text());
  // 顯示
  const panel = document.getElementById("blocksResult"); panel.innerHTML = "<h4>排程結果</h4>";
  const tbl = document.createElement("table"); tbl.style.width="100%"; tbl.innerHTML="<tr><th>開始</th><th>結束</th><th>課程</th></tr>";
  JSON.parse(arr).forEach(r=>{ const tr=document.createElement("tr"); tr.innerHTML=`<td>${r.start}</td><td>${r.end}</td><td>${r.course_name}</td>`; tbl.appendChild(tr); });
  panel.appendChild(tbl);
  // 同時把這個排程送去啟動提醒伺服器背景工作
  const schedule = JSON.parse(arr).map(x=>({start:x.start,end:x.end,course_name:x.course_name}));
  const r = await fetch("/api/start_reminders", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(schedule)});
  if(r.ok) alert("已啟動伺服器端提醒");
});

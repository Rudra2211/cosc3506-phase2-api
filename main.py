"""COSC-3506 Phase 2: student academic profile API (FastAPI)."""
import re
import threading
from typing import List

from bs4 import BeautifulSoup
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

app = FastAPI(title="Student Profile API")
PAST_STATUSES = {"Completed", "In-Progress", "Attempted"}
# shortcut: in-memory store, lost on restart/sleep; upgrade to a DB if persistence is needed
STUDENTS: dict = {}  # {student_id: {"history": [...], "plan": [...]}}
LOCK = threading.Lock()


class HistoryItem(BaseModel):
    course_code: str
    term: str
    credits_earned: int = 0
    status: str


class HistoryBody(BaseModel):
    history: List[HistoryItem]


class PlanItem(BaseModel):
    course_code: str
    term: str


class PlanBody(BaseModel):
    planned_courses: List[PlanItem]


def _grade_rank(g: str):
    g = (g or "").strip()
    if re.fullmatch(r"\d+(\.\d+)?", g):
        return (2, float(g))
    if re.fullmatch(r"[A-EF][+-]?", g, re.I):
        return (1, 0.0)
    return (0, 0.0)


def parse_transcript(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    best: dict = {}
    for t in soup.find_all("table"):
        ths = [th.get_text(strip=True) for th in t.find_all("th")]
        if not ("Status" in ths and "Course" in ths and "Credits" in ths):
            continue
        for r in t.find_all("tr"):
            tds = [c.get_text(" ", strip=True) for c in r.find_all("td")]
            if len(tds) < 6 or not tds[1]:
                continue
            status, course, grade, term, credits = tds[0], tds[1], tds[3], tds[4], tds[5]
            if status not in PAST_STATUSES or not term:
                continue
            try:
                ce = int(credits)
            except ValueError:
                ce = 0
            key = (course, term)
            cand = (_grade_rank(grade), ce)
            if key not in best or cand > best[key][0]:
                best[key] = (cand, {"course_code": course, "term": term,
                                    "credits_earned": ce, "status": status})
    return [v[1] for v in best.values()]


def _student(sid: str) -> dict:
    s = STUDENTS.get(sid)
    if s is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return s


@app.get("/")
def root():
    return {"status": "ok", "service": "student-profile-api"}


@app.post("/api/v1/students/{sid}/history/import", status_code=201)
async def import_history(sid: str, file: UploadFile = File(...)):
    html = (await file.read()).decode("utf-8", errors="replace")
    records = parse_transcript(html)
    with LOCK:
        s = STUDENTS.setdefault(sid, {"history": [], "plan": []})
        s["history"] = records
    return {"status": "success", "past_courses_imported": len(records)}


@app.put("/api/v1/students/{sid}/history")
def put_history(sid: str, body: HistoryBody):
    with LOCK:
        _student(sid)["history"] = [h.model_dump() for h in body.history]
    return {"status": "success", "message": "Academic history updated successfully"}


@app.delete("/api/v1/students/{sid}/history")
def delete_history(sid: str):
    with LOCK:
        _student(sid)["history"] = []
    return {"status": "success", "message": "Academic history cleared"}


def _set_plan(sid: str, body: PlanBody):
    with LOCK:
        _student(sid)["plan"] = [p.model_dump() for p in body.planned_courses]
    return {"status": "success", "planned_courses_saved": len(body.planned_courses)}


@app.post("/api/v1/students/{sid}/plan")
def post_plan(sid: str, body: PlanBody):
    return _set_plan(sid, body)


@app.put("/api/v1/students/{sid}/plan")
def put_plan(sid: str, body: PlanBody):
    return _set_plan(sid, body)


@app.delete("/api/v1/students/{sid}/plan")
def delete_plan(sid: str):
    with LOCK:
        _student(sid)["plan"] = []
    return {"status": "success", "message": "Plan cleared"}


@app.get("/api/v1/students/{sid}/profile")
def profile(sid: str):
    with LOCK:
        s = _student(sid)
        return {"student_id": sid, "history": list(s["history"]), "plan": list(s["plan"])}

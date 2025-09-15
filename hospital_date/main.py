# main.py
from fastapi import FastAPI, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import date, datetime, timedelta
import calendar

from models import Booking
from database import SessionLocal, engine

# Создаём таблицы
Booking.metadata.create_all(bind=engine)

app = FastAPI(debug=True)
templates = Jinja2Templates(directory="templates")

ACCESS_PASSWORD = "12345"
from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key="supersecretkey123")

WORKERS = ["Хирург", "Терапевт", "Ортопед"]

def generate_time_slots():
    """Генерирует слоты с 9:00 до 18:30 с шагом 30 минут"""
    slots = []
    start_hour = 9
    end_hour = 19
    for hour in range(start_hour, end_hour):
        for minute in (0, 30):
            slots.append(f"{hour:02d}:{minute:02d}")
    return slots

def get_week_dates(start_date: date):
    """Возвращает список дат недели (Пн-Вс), начиная с start_date (должен быть понедельник)"""
    return [start_date + timedelta(days=i) for i in range(7)]

def get_monday(d: date):
    """Возвращает дату понедельника текущей недели"""
    return d - timedelta(days=d.weekday())

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/calendar")
    return RedirectResponse(url="/password")

@app.get("/password", response_class=HTMLResponse)
async def password_page(request: Request):
    return templates.TemplateResponse("password.html", {"request": request})

@app.post("/password", response_class=HTMLResponse)
async def check_password(request: Request, password: str = Form(...)):
    if password == ACCESS_PASSWORD:
        request.session["authenticated"] = True
        return RedirectResponse(url="/calendar", status_code=303)
    return templates.TemplateResponse(
        "password.html",
        {"request": request, "error": "Неверный пароль"}
    )

@app.get("/calendar", response_class=HTMLResponse)
async def calendar_view(
    request: Request,
    start_date: str = None,
    db: Session = Depends(get_db)
):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/password")

    if start_date:
        try:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
            if start_date.weekday() != 0:
                start_date = get_monday(start_date)
        except ValueError:
            start_date = get_monday(date.today())
    else:
        start_date = get_monday(date.today())

    week_dates = get_week_dates(start_date)
    current_month = start_date.month
    current_year = start_date.year
    month_name = calendar.month_name[current_month]

    end_date = week_dates[-1]
    bookings = db.query(Booking).filter(
        Booking.date >= week_dates[0],
        Booking.date <= end_date
    ).all()

    bookings_by_date_worker = {}
    for b in bookings:
        b_date = b.date
        if b_date not in bookings_by_date_worker:
            bookings_by_date_worker[b_date] = {worker: [] for worker in WORKERS}
        bookings_by_date_worker[b_date][b.worker].append(b)

    for day_date, workers_dict in bookings_by_date_worker.items():
        for worker in workers_dict:
            workers_dict[worker].sort(key=lambda x: x.time)

    prev_week = start_date - timedelta(weeks=1)
    next_week = start_date + timedelta(weeks=1)

    if current_month == 12:
        next_month_year = current_year + 1
        next_month_num = 1
    else:
        next_month_year = current_year
        next_month_num = current_month + 1

    first_day_next_month = date(next_month_year, next_month_num, 1)
    next_month_monday = get_monday(first_day_next_month)

    return templates.TemplateResponse(
        "calendar.html",
        {
            "request": request,
            "week_dates": week_dates,
            "month_name": month_name,
            "year": current_year,
            "bookings_by_date_worker": bookings_by_date_worker,
            "workers": WORKERS,
            "time_slots": generate_time_slots(),
            "today": date.today(),
            "start_date": start_date,
            "prev_week": prev_week,
            "next_week": next_week,
            "next_month_monday": next_month_monday,
        }
    )

# ИСПРАВЛЕНО: принимаем start_date из формы
@app.post("/add_booking", response_class=HTMLResponse)
async def add_booking(
    request: Request,
    surname: str = Form(...),
    date_str: str = Form(...),
    worker: str = Form(...),
    time: str = Form(...),
    start_date: str = Form(...),  # ← ПРИНИМАЕМ start_date
    db: Session = Depends(get_db)
):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/password")

    if worker not in WORKERS:
        return RedirectResponse(url="/calendar?error=Неверный сотрудник", status_code=303)

    try:
        booking_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url="/calendar?error=Неверная дата", status_code=303)

    # Проверяем, занято ли это время у этого сотрудника в этот день
    existing = db.query(Booking).filter(
        Booking.date == booking_date,
        Booking.worker == worker,
        Booking.time == time
    ).first()

    if existing:
        return RedirectResponse(
            url=f"/calendar?start_date={start_date}&error=Время {time} у {worker} уже занято!",
            status_code=303
        )

    new_booking = Booking(
        surname=surname.strip(),
        date=booking_date,
        worker=worker,
        time=time
    )
    db.add(new_booking)
    db.commit()

    # Редирект с сохранением недели
    return RedirectResponse(url=f"/calendar?start_date={start_date}", status_code=303)

# Удаление записи
@app.post("/delete_booking/{booking_id}", response_class=HTMLResponse)
async def delete_booking(
    request: Request,
    booking_id: int,
    db: Session = Depends(get_db)
):
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/password")

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        return RedirectResponse(url="/calendar?error=Запись не найдена", status_code=303)

    db.delete(booking)
    db.commit()

    # Получаем start_date из Referer или возвращаем на текущую неделю
    referer = request.headers.get("Referer")
    if referer and "start_date=" in referer:
        return RedirectResponse(referer, status_code=303)
    else:
        return RedirectResponse(url="/calendar", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/password")

# python3 -m uvicorn main:app --reload
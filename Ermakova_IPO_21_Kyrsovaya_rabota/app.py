import os
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
INSTANCE_DIR = BASE_DIR / "instance"
DATABASE = INSTANCE_DIR / "mts_tariffs.db"


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key-for-course-project")
app.config["DATABASE"] = str(DATABASE)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    INSTANCE_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    for script_name in ("schema.sql", "seed.sql"):
        script_path = BASE_DIR / script_name
        db.executescript(script_path.read_text(encoding="utf-8"))
    db.commit()
    db.close()


@app.before_request
def ensure_database_exists():
    if not DATABASE.exists():
        init_db()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute(
        """
        SELECT users.*, roles.name AS role_name
        FROM users
        JOIN roles ON roles.id = users.role_id
        WHERE users.id = ?
        """,
        (user_id,),
    ).fetchone()


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "hotline": "8 800 555-01-77",
    }


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if not session.get("user_id"):
            flash("Для доступа к разделу необходимо войти в аккаунт.", "warning")
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(**kwargs):
            user = current_user()
            if not user or user["role_name"] not in roles:
                flash("Недостаточно прав для выполнения операции.", "danger")
                return redirect(url_for("index"))
            return view(**kwargs)

        return wrapped_view

    return decorator


def verify_password(stored_hash, password, user_id):
    if stored_hash.startswith("plain:"):
        is_valid = stored_hash.removeprefix("plain:") == password
        if is_valid:
            get_db().execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (generate_password_hash(password), user_id),
            )
            get_db().commit()
        return is_valid
    return check_password_hash(stored_hash, password)


def get_categories():
    return get_db().execute(
        "SELECT * FROM client_categories ORDER BY priority, name"
    ).fetchall()


def get_services():
    return get_db().execute("SELECT * FROM services ORDER BY name").fetchall()


def get_tariffs(filters=None):
    filters = filters or {}
    clauses = ["tariffs.is_active = 1"]
    params = []

    if filters.get("search"):
        clauses.append("(tariffs.name LIKE ? OR tariffs.short_description LIKE ?)")
        search = f"%{filters['search']}%"
        params.extend([search, search])
    if filters.get("category_id"):
        clauses.append("tariffs.category_id = ?")
        params.append(filters["category_id"])
    if filters.get("max_price"):
        clauses.append("tariff_parameters.monthly_price <= ?")
        params.append(filters["max_price"])
    if filters.get("min_gb"):
        clauses.append("(tariff_parameters.mobile_gb >= ? OR tariff_parameters.unlimited_mobile = 1)")
        params.append(filters["min_gb"])
    if filters.get("need_unlimited"):
        clauses.append("tariff_parameters.unlimited_mobile = 1")
    if filters.get("need_home_internet"):
        clauses.append("tariff_parameters.home_internet_included = 1")

    where_sql = " AND ".join(clauses)
    return get_db().execute(
        f"""
        SELECT
            tariffs.*,
            client_categories.name AS category_name,
            client_categories.priority AS category_priority,
            tariff_parameters.mobile_gb,
            tariff_parameters.unlimited_mobile,
            tariff_parameters.sms,
            tariff_parameters.minutes,
            tariff_parameters.home_internet_included,
            tariff_parameters.home_speed_mbps,
            tariff_parameters.tv_channels,
            tariff_parameters.cinema_included,
            tariff_parameters.parental_control,
            tariff_parameters.spam_protection,
            tariff_parameters.monthly_price,
            COALESCE(GROUP_CONCAT(services.name, ', '), 'Без дополнительных услуг') AS services
        FROM tariffs
        JOIN client_categories ON client_categories.id = tariffs.category_id
        JOIN tariff_parameters ON tariff_parameters.tariff_id = tariffs.id
        LEFT JOIN tariff_services ON tariff_services.tariff_id = tariffs.id
        LEFT JOIN services ON services.id = tariff_services.service_id
        WHERE {where_sql}
        GROUP BY tariffs.id
        ORDER BY tariff_parameters.monthly_price, tariffs.name
        """,
        params,
    ).fetchall()


def get_tariff(tariff_id):
    return get_db().execute(
        """
        SELECT
            tariffs.*,
            client_categories.name AS category_name,
            client_categories.priority AS category_priority,
            tariff_parameters.mobile_gb,
            tariff_parameters.unlimited_mobile,
            tariff_parameters.sms,
            tariff_parameters.minutes,
            tariff_parameters.home_internet_included,
            tariff_parameters.home_speed_mbps,
            tariff_parameters.tv_channels,
            tariff_parameters.cinema_included,
            tariff_parameters.parental_control,
            tariff_parameters.spam_protection,
            tariff_parameters.monthly_price,
            COALESCE(GROUP_CONCAT(services.name, ', '), 'Без дополнительных услуг') AS services
        FROM tariffs
        JOIN client_categories ON client_categories.id = tariffs.category_id
        JOIN tariff_parameters ON tariff_parameters.tariff_id = tariffs.id
        LEFT JOIN tariff_services ON tariff_services.tariff_id = tariffs.id
        LEFT JOIN services ON services.id = tariff_services.service_id
        WHERE tariffs.id = ?
        GROUP BY tariffs.id
        """,
        (tariff_id,),
    ).fetchone()


def parse_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def score_tariff(tariff, preferences, categories_by_id):
    weights = {
        row["code"]: row["weight"]
        for row in get_db().execute("SELECT code, weight FROM criteria").fetchall()
    }
    desired_price = max(preferences["desired_price"], 1)
    desired_gb = max(preferences["desired_gb"], 1)
    desired_minutes = max(preferences["desired_minutes"], 1)
    desired_sms = max(preferences["desired_sms"], 1)
    desired_home_speed = max(preferences["desired_home_speed"], 1)

    if tariff["monthly_price"] <= desired_price:
        price_score = 1 - min((desired_price - tariff["monthly_price"]) / desired_price, 1) * 0.25
    else:
        price_score = max(0, 1 - (tariff["monthly_price"] - desired_price) / desired_price * 1.3)

    if preferences["need_unlimited"]:
        internet_score = 1 if tariff["unlimited_mobile"] else min(tariff["mobile_gb"] / 80, 0.75)
    elif tariff["unlimited_mobile"]:
        internet_score = 1
    else:
        internet_score = min(tariff["mobile_gb"] / desired_gb, 1)

    minutes_score = min(tariff["minutes"] / desired_minutes, 1)
    sms_score = 1 if desired_sms == 1 else min(tariff["sms"] / desired_sms, 1)

    if preferences["need_home_internet"]:
        if tariff["home_internet_included"]:
            home_score = min(tariff["home_speed_mbps"] / desired_home_speed, 1)
        else:
            home_score = 0
    else:
        home_score = 1 if not tariff["home_internet_included"] else 0.82

    requested_category_id = preferences.get("preference_category_id")
    if requested_category_id:
        requested = categories_by_id.get(requested_category_id)
        if requested and requested["id"] == tariff["category_id"]:
            category_score = 1
        elif requested:
            distance = abs(requested["priority"] - tariff["category_priority"])
            category_score = max(0.4, 1 - distance * 0.25)
        else:
            category_score = 0.8
    else:
        category_score = 0.8

    weighted = (
        price_score * weights.get("price", 0.30)
        + internet_score * weights.get("internet", 0.22)
        + minutes_score * weights.get("minutes", 0.16)
        + sms_score * weights.get("sms", 0.08)
        + home_score * weights.get("home", 0.14)
        + category_score * weights.get("category", 0.10)
    )
    return round(weighted, 4)


def collect_preferences(form):
    return {
        "desired_price": parse_int(form.get("desired_price"), 900),
        "desired_gb": parse_int(form.get("desired_gb"), 20),
        "need_unlimited": 1 if form.get("need_unlimited") == "on" else 0,
        "desired_minutes": parse_int(form.get("desired_minutes"), 600),
        "desired_sms": parse_int(form.get("desired_sms"), 100),
        "need_home_internet": 1 if form.get("need_home_internet") == "on" else 0,
        "desired_home_speed": parse_int(form.get("desired_home_speed"), 100),
        "preference_category_id": parse_int(form.get("preference_category_id"), 0) or None,
    }


def ranked_tariffs(preferences):
    categories = get_categories()
    categories_by_id = {row["id"]: row for row in categories}
    tariffs = get_tariffs()
    ranked = []
    for tariff in tariffs:
        score = score_tariff(tariff, preferences, categories_by_id)
        ranked.append({"tariff": tariff, "score": score, "percent": round(score * 100)})
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def record_selection(preferences, recommended):
    user_id = session.get("user_id")
    get_db().execute(
        """
        INSERT INTO selection_history
        (user_id, tariff_id, desired_price, desired_gb, need_unlimited, desired_minutes,
         desired_sms, need_home_internet, desired_home_speed, preference_category_id, score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            recommended["tariff"]["id"],
            preferences["desired_price"],
            preferences["desired_gb"],
            preferences["need_unlimited"],
            preferences["desired_minutes"],
            preferences["desired_sms"],
            preferences["need_home_internet"],
            preferences["desired_home_speed"],
            preferences["preference_category_id"],
            recommended["score"],
        ),
    )
    get_db().commit()


def analytics_data():
    tariff_frequency = get_db().execute(
        """
        SELECT tariffs.name, COUNT(selection_history.id) AS total
        FROM selection_history
        JOIN tariffs ON tariffs.id = selection_history.tariff_id
        GROUP BY tariffs.id
        ORDER BY total DESC, tariffs.name
        LIMIT 10
        """
    ).fetchall()
    category_distribution = get_db().execute(
        """
        SELECT client_categories.name, COUNT(selection_history.id) AS total
        FROM selection_history
        LEFT JOIN client_categories
            ON client_categories.id = selection_history.preference_category_id
        GROUP BY client_categories.id
        ORDER BY total DESC
        """
    ).fetchall()
    return tariff_frequency, category_distribution


@app.route("/")
def index():
    filters = {
        "search": request.args.get("search", "").strip(),
        "category_id": parse_int(request.args.get("category_id"), 0) or None,
        "max_price": parse_int(request.args.get("max_price"), 0) or None,
        "min_gb": parse_int(request.args.get("min_gb"), 0) or None,
        "need_unlimited": request.args.get("need_unlimited") == "1",
        "need_home_internet": request.args.get("need_home_internet") == "1",
    }
    tariffs = get_tariffs(filters)
    newest = get_db().execute(
        """
        SELECT tariffs.*, tariff_parameters.monthly_price, tariff_parameters.unlimited_mobile,
               tariff_parameters.mobile_gb, tariff_parameters.home_internet_included,
               tariff_parameters.home_speed_mbps
        FROM tariffs
        JOIN tariff_parameters ON tariff_parameters.tariff_id = tariffs.id
        WHERE tariffs.is_new = 1 AND tariffs.is_active = 1
        ORDER BY tariffs.id DESC
        LIMIT 1
        """
    ).fetchone()
    history = get_db().execute(
        """
        SELECT view_history.viewed_at, tariffs.name, tariffs.id, tariff_parameters.monthly_price
        FROM view_history
        JOIN tariffs ON tariffs.id = view_history.tariff_id
        JOIN tariff_parameters ON tariff_parameters.tariff_id = tariffs.id
        WHERE view_history.user_id IS ? OR (? IS NULL AND view_history.user_id IS NULL)
        ORDER BY view_history.viewed_at DESC
        LIMIT 8
        """,
        (session.get("user_id"), session.get("user_id")),
    ).fetchall()
    return render_template(
        "index.html",
        tariffs=tariffs,
        categories=get_categories(),
        newest=newest,
        history=history,
        filters=filters,
    )


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Логин и пароль нельзя оставлять пустыми.", "danger")
            return render_template("login.html")

        user = get_db().execute(
            """
            SELECT users.*, roles.name AS role_name
            FROM users JOIN roles ON roles.id = users.role_id
            WHERE users.username = ?
            """,
            (username,),
        ).fetchone()
        if user and verify_password(user["password_hash"], password, user["id"]):
            session.clear()
            session["user_id"] = user["id"]
            flash(f"С возвращением, {user['full_name']}!", "success")
            return redirect(url_for("index"))
        flash("Неверный логин или пароль.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из аккаунта.", "info")
    return redirect(url_for("index"))


@app.route("/search", methods=("POST",))
def search_results():
    preferences = collect_preferences(request.form)
    results = ranked_tariffs(preferences)
    if results:
        record_selection(preferences, results[0])
    return render_template(
        "results.html",
        results=results[:8],
        preferences=preferences,
        categories=get_categories(),
    )


@app.route("/tariffs/<int:tariff_id>")
def tariff_detail(tariff_id):
    tariff = get_tariff(tariff_id)
    if tariff is None:
        flash("Тариф не найден.", "warning")
        return redirect(url_for("index"))
    get_db().execute(
        "INSERT INTO view_history (user_id, tariff_id) VALUES (?, ?)",
        (session.get("user_id"), tariff_id),
    )
    get_db().commit()
    reviews = get_db().execute(
        """
        SELECT reviews.*, COALESCE(users.full_name, 'Гость') AS author
        FROM reviews
        LEFT JOIN users ON users.id = reviews.user_id
        WHERE reviews.tariff_id = ?
        ORDER BY reviews.created_at DESC
        """,
        (tariff_id,),
    ).fetchall()
    return render_template("tariff_detail.html", tariff=tariff, reviews=reviews)


@app.route("/compare")
def compare():
    ids = [parse_int(value) for value in request.args.getlist("ids") if parse_int(value)]
    if not ids:
        ids = [parse_int(value) for value in request.args.get("ids", "").split(",") if parse_int(value)]
    if not ids:
        flash("Выберите тарифы для сравнения.", "warning")
        return redirect(url_for("index"))
    placeholders = ",".join("?" for _ in ids)
    tariffs = get_db().execute(
        f"""
        SELECT tariffs.*, client_categories.name AS category_name,
               tariff_parameters.mobile_gb, tariff_parameters.unlimited_mobile,
               tariff_parameters.sms, tariff_parameters.minutes,
               tariff_parameters.home_internet_included, tariff_parameters.home_speed_mbps,
               tariff_parameters.tv_channels, tariff_parameters.cinema_included,
               tariff_parameters.parental_control, tariff_parameters.spam_protection,
               tariff_parameters.monthly_price
        FROM tariffs
        JOIN client_categories ON client_categories.id = tariffs.category_id
        JOIN tariff_parameters ON tariff_parameters.tariff_id = tariffs.id
        WHERE tariffs.id IN ({placeholders})
        ORDER BY tariff_parameters.monthly_price
        """,
        ids,
    ).fetchall()
    return render_template("compare.html", tariffs=tariffs)


@app.route("/analytics")
@roles_required("admin", "manager")
def analytics():
    tariff_frequency, category_distribution = analytics_data()
    return render_template(
        "analytics.html",
        tariff_frequency=tariff_frequency,
        category_distribution=category_distribution,
    )


@app.route("/manage")
@roles_required("admin", "manager")
def manage_dashboard():
    tariff_frequency, category_distribution = analytics_data()
    counts = {
        "tariffs": get_db().execute("SELECT COUNT(*) AS c FROM tariffs").fetchone()["c"],
        "history": get_db().execute("SELECT COUNT(*) AS c FROM selection_history").fetchone()["c"],
        "categories": get_db().execute("SELECT COUNT(*) AS c FROM client_categories").fetchone()["c"],
        "services": get_db().execute("SELECT COUNT(*) AS c FROM services").fetchone()["c"],
    }
    return render_template(
        "manage/dashboard.html",
        counts=counts,
        tariff_frequency=tariff_frequency,
        category_distribution=category_distribution,
    )


@app.route("/manage/tariffs")
@roles_required("admin", "manager")
def manage_tariffs():
    return render_template("manage/tariffs.html", tariffs=get_tariffs({}), categories=get_categories())


def tariff_form_data(form):
    return {
        "name": form.get("name", "").strip(),
        "short_description": form.get("short_description", "").strip(),
        "category_id": parse_int(form.get("category_id"), 1),
        "is_new": 1 if form.get("is_new") == "on" else 0,
        "is_active": 1 if form.get("is_active") == "on" else 0,
        "mobile_gb": parse_int(form.get("mobile_gb")),
        "unlimited_mobile": 1 if form.get("unlimited_mobile") == "on" else 0,
        "sms": parse_int(form.get("sms")),
        "minutes": parse_int(form.get("minutes")),
        "home_internet_included": 1 if form.get("home_internet_included") == "on" else 0,
        "home_speed_mbps": parse_int(form.get("home_speed_mbps")),
        "tv_channels": parse_int(form.get("tv_channels")),
        "cinema_included": 1 if form.get("cinema_included") == "on" else 0,
        "parental_control": 1 if form.get("parental_control") == "on" else 0,
        "spam_protection": 1 if form.get("spam_protection") == "on" else 0,
        "monthly_price": parse_int(form.get("monthly_price")),
        "service_ids": [parse_int(value) for value in form.getlist("service_ids")],
    }


def save_tariff_services(tariff_id, service_ids):
    db = get_db()
    db.execute("DELETE FROM tariff_services WHERE tariff_id = ?", (tariff_id,))
    db.executemany(
        "INSERT INTO tariff_services (tariff_id, service_id) VALUES (?, ?)",
        [(tariff_id, service_id) for service_id in service_ids if service_id],
    )


@app.route("/manage/tariffs/new", methods=("GET", "POST"))
@roles_required("admin", "manager")
def tariff_create():
    if request.method == "POST":
        data = tariff_form_data(request.form)
        if not data["name"] or not data["short_description"] or data["monthly_price"] <= 0:
            flash("Название, описание и стоимость обязательны.", "danger")
        else:
            cursor = get_db().execute(
                """
                INSERT INTO tariffs (name, short_description, category_id, is_new, is_active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (data["name"], data["short_description"], data["category_id"], data["is_new"], data["is_active"]),
            )
            tariff_id = cursor.lastrowid
            get_db().execute(
                """
                INSERT INTO tariff_parameters
                (tariff_id, mobile_gb, unlimited_mobile, sms, minutes, home_internet_included,
                 home_speed_mbps, tv_channels, cinema_included, parental_control, spam_protection, monthly_price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tariff_id,
                    data["mobile_gb"],
                    data["unlimited_mobile"],
                    data["sms"],
                    data["minutes"],
                    data["home_internet_included"],
                    data["home_speed_mbps"],
                    data["tv_channels"],
                    data["cinema_included"],
                    data["parental_control"],
                    data["spam_protection"],
                    data["monthly_price"],
                ),
            )
            save_tariff_services(tariff_id, data["service_ids"])
            get_db().commit()
            flash("Тариф создан.", "success")
            return redirect(url_for("manage_tariffs"))
    return render_template(
        "manage/tariff_form.html",
        tariff=None,
        categories=get_categories(),
        services=get_services(),
        selected_services=[],
    )


@app.route("/manage/tariffs/<int:tariff_id>/edit", methods=("GET", "POST"))
@roles_required("admin", "manager")
def tariff_edit(tariff_id):
    tariff = get_tariff(tariff_id)
    if tariff is None:
        flash("Тариф не найден.", "warning")
        return redirect(url_for("manage_tariffs"))
    if request.method == "POST":
        data = tariff_form_data(request.form)
        if not data["name"] or not data["short_description"] or data["monthly_price"] <= 0:
            flash("Название, описание и стоимость обязательны.", "danger")
        else:
            get_db().execute(
                """
                UPDATE tariffs
                SET name = ?, short_description = ?, category_id = ?, is_new = ?, is_active = ?
                WHERE id = ?
                """,
                (
                    data["name"],
                    data["short_description"],
                    data["category_id"],
                    data["is_new"],
                    data["is_active"],
                    tariff_id,
                ),
            )
            get_db().execute(
                """
                UPDATE tariff_parameters
                SET mobile_gb = ?, unlimited_mobile = ?, sms = ?, minutes = ?,
                    home_internet_included = ?, home_speed_mbps = ?, tv_channels = ?,
                    cinema_included = ?, parental_control = ?, spam_protection = ?, monthly_price = ?
                WHERE tariff_id = ?
                """,
                (
                    data["mobile_gb"],
                    data["unlimited_mobile"],
                    data["sms"],
                    data["minutes"],
                    data["home_internet_included"],
                    data["home_speed_mbps"],
                    data["tv_channels"],
                    data["cinema_included"],
                    data["parental_control"],
                    data["spam_protection"],
                    data["monthly_price"],
                    tariff_id,
                ),
            )
            save_tariff_services(tariff_id, data["service_ids"])
            get_db().commit()
            flash("Тариф обновлен.", "success")
            return redirect(url_for("manage_tariffs"))
    selected_services = [
        row["service_id"]
        for row in get_db().execute("SELECT service_id FROM tariff_services WHERE tariff_id = ?", (tariff_id,))
    ]
    return render_template(
        "manage/tariff_form.html",
        tariff=tariff,
        categories=get_categories(),
        services=get_services(),
        selected_services=selected_services,
    )


@app.route("/manage/tariffs/<int:tariff_id>/delete", methods=("POST",))
@roles_required("admin", "manager")
def tariff_delete(tariff_id):
    get_db().execute("DELETE FROM tariffs WHERE id = ?", (tariff_id,))
    get_db().commit()
    flash("Тариф удален.", "info")
    return redirect(url_for("manage_tariffs"))


@app.route("/manage/categories", methods=("GET", "POST"))
@roles_required("admin", "manager")
def manage_categories():
    if request.method == "POST":
        category_id = parse_int(request.form.get("category_id"))
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        priority = parse_int(request.form.get("priority"), 1)
        if not name:
            flash("Название категории обязательно.", "danger")
        elif category_id:
            get_db().execute(
                "UPDATE client_categories SET name = ?, description = ?, priority = ? WHERE id = ?",
                (name, description, priority, category_id),
            )
            get_db().commit()
            flash("Категория обновлена.", "success")
        else:
            get_db().execute(
                "INSERT INTO client_categories (name, description, priority) VALUES (?, ?, ?)",
                (name, description, priority),
            )
            get_db().commit()
            flash("Категория создана.", "success")
        return redirect(url_for("manage_categories"))
    return render_template("manage/categories.html", categories=get_categories())


@app.route("/manage/categories/<int:category_id>/delete", methods=("POST",))
@roles_required("admin", "manager")
def category_delete(category_id):
    try:
        get_db().execute("DELETE FROM client_categories WHERE id = ?", (category_id,))
        get_db().commit()
        flash("Категория удалена.", "info")
    except sqlite3.IntegrityError:
        flash("Категория используется тарифами, удаление невозможно.", "danger")
    return redirect(url_for("manage_categories"))


@app.route("/manage/services", methods=("GET", "POST"))
@roles_required("admin", "manager")
def manage_services():
    if request.method == "POST":
        service_id = parse_int(request.form.get("service_id"))
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        monthly_price = parse_int(request.form.get("monthly_price"))
        is_active = 1 if request.form.get("is_active") == "on" else 0
        if not name or not description:
            flash("Название и описание услуги обязательны.", "danger")
        elif service_id:
            get_db().execute(
                """
                UPDATE services
                SET name = ?, description = ?, monthly_price = ?, is_active = ?
                WHERE id = ?
                """,
                (name, description, monthly_price, is_active, service_id),
            )
            get_db().commit()
            flash("Услуга обновлена.", "success")
        else:
            get_db().execute(
                "INSERT INTO services (name, description, monthly_price, is_active) VALUES (?, ?, ?, ?)",
                (name, description, monthly_price, is_active),
            )
            get_db().commit()
            flash("Услуга создана.", "success")
        return redirect(url_for("manage_services"))
    return render_template("manage/services.html", services=get_services())


@app.route("/manage/services/<int:service_id>/delete", methods=("POST",))
@roles_required("admin", "manager")
def service_delete(service_id):
    get_db().execute("DELETE FROM services WHERE id = ?", (service_id,))
    get_db().commit()
    flash("Услуга удалена.", "info")
    return redirect(url_for("manage_services"))


@app.route("/manage/history", methods=("GET", "POST"))
@roles_required("admin", "manager")
def manage_history():
    if request.method == "POST":
        history_id = parse_int(request.form.get("history_id"))
        data = {
            "user_id": parse_int(request.form.get("user_id")) or None,
            "tariff_id": parse_int(request.form.get("tariff_id")),
            "desired_price": parse_int(request.form.get("desired_price"), 900),
            "desired_gb": parse_int(request.form.get("desired_gb"), 20),
            "need_unlimited": 1 if request.form.get("need_unlimited") == "on" else 0,
            "desired_minutes": parse_int(request.form.get("desired_minutes"), 600),
            "desired_sms": parse_int(request.form.get("desired_sms"), 100),
            "need_home_internet": 1 if request.form.get("need_home_internet") == "on" else 0,
            "desired_home_speed": parse_int(request.form.get("desired_home_speed"), 100),
            "preference_category_id": parse_int(request.form.get("preference_category_id")) or None,
            "score": float(request.form.get("score") or 0),
        }
        if not data["tariff_id"]:
            flash("Для истории необходимо выбрать тариф.", "danger")
        elif history_id:
            get_db().execute(
                """
                UPDATE selection_history
                SET user_id = ?, tariff_id = ?, desired_price = ?, desired_gb = ?, need_unlimited = ?,
                    desired_minutes = ?, desired_sms = ?, need_home_internet = ?, desired_home_speed = ?,
                    preference_category_id = ?, score = ?
                WHERE id = ?
                """,
                (
                    data["user_id"],
                    data["tariff_id"],
                    data["desired_price"],
                    data["desired_gb"],
                    data["need_unlimited"],
                    data["desired_minutes"],
                    data["desired_sms"],
                    data["need_home_internet"],
                    data["desired_home_speed"],
                    data["preference_category_id"],
                    data["score"],
                    history_id,
                ),
            )
            get_db().commit()
            flash("Запись истории обновлена.", "success")
        else:
            get_db().execute(
                """
                INSERT INTO selection_history
                (user_id, tariff_id, desired_price, desired_gb, need_unlimited, desired_minutes,
                 desired_sms, need_home_internet, desired_home_speed, preference_category_id, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["user_id"],
                    data["tariff_id"],
                    data["desired_price"],
                    data["desired_gb"],
                    data["need_unlimited"],
                    data["desired_minutes"],
                    data["desired_sms"],
                    data["need_home_internet"],
                    data["desired_home_speed"],
                    data["preference_category_id"],
                    data["score"],
                ),
            )
            get_db().commit()
            flash("Запись истории создана.", "success")
        return redirect(url_for("manage_history"))

    history = get_db().execute(
        """
        SELECT selection_history.*, tariffs.name AS tariff_name,
               COALESCE(users.full_name, 'Гость') AS user_name,
               client_categories.name AS category_name
        FROM selection_history
        JOIN tariffs ON tariffs.id = selection_history.tariff_id
        LEFT JOIN users ON users.id = selection_history.user_id
        LEFT JOIN client_categories ON client_categories.id = selection_history.preference_category_id
        ORDER BY selection_history.created_at DESC
        """
    ).fetchall()
    users = get_db().execute("SELECT id, full_name FROM users ORDER BY full_name").fetchall()
    return render_template(
        "manage/history.html",
        history=history,
        tariffs=get_tariffs({}),
        users=users,
        categories=get_categories(),
    )


@app.route("/manage/history/<int:history_id>/delete", methods=("POST",))
@roles_required("admin", "manager")
def history_delete(history_id):
    get_db().execute("DELETE FROM selection_history WHERE id = ?", (history_id,))
    get_db().commit()
    flash("Запись истории удалена.", "info")
    return redirect(url_for("manage_history"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_ENV") != "production")

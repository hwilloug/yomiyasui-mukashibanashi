import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask_session import Session
from functools import wraps
import requests
from sudachipy import tokenizer, dictionary
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Configure database
db = SQL("sqlite:///stories.db")

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

def login_required(f):
    """
    Decorate routes to require login.

    https://flask.palletsprojects.com/en/1.1.x/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


@app.route("/")
def index():
    stories = db.execute("SELECT id,title FROM stories;")
    return render_template('index.html', stories=stories)


@app.route("/login", methods=["GET", "POST"])
def login():

    if "user_id" in session.keys():
        session.clear()

    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        if not username:
            flash("Please enter a username.", "warning")
            return redirect(request.path)

        elif not password:
            flash("Please enter a password.", "warning")
            return redirect(request.path)

        users = db.execute("SELECT * FROM users WHERE username = ?", username)

        if len(users) != 1 or not check_password_hash(users[0]["hash"], password):
            flash("Username and/or password is incorrect.", "danger")
            return redirect(request.path)

        session["user_id"] = users[0]["id"]

        flash("Successfully logged in.", "primary")
        return redirect("/")

    return render_template("login.html")

@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    flash("Successfully logged out.", "primary")
    return redirect("/login")

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":
        name = request.form.get("username")
        password = request.form.get("password")
        confirm_password = request.form.get("confirmation")

        if not name:
            flash("Please enter a username.", "danger")
            return redirect(request.path)

        if db.execute("SELECT username FROM users WHERE username=?", name):
            flash("User already exists.", "danger")
            return redirect(request.path)

        if not password or not confirm_password:
            flash("Please enter a password and confirm it.", "danger")
            return redirect(request.path)

        if password != confirm_password:
            flash("Passwords do not match. Please try again.", "danger")
            return redirect(request.path)

        db.execute("INSERT INTO users (username, hash) VALUES (?, ?);", name, generate_password_hash(password))

        flash("User successfully created. Please log in to continue.", "primary")
        return redirect("/login")

    return render_template("register.html")


@app.route("/stories/<int:story_id>")
def render_story(story_id):

    story = db.execute("SELECT * FROM stories WHERE id=?", story_id)[0]
    story["story"] = story["story"].split('\\n')

    tokenizer_obj = dictionary.Dictionary().create()

    mode = tokenizer.Tokenizer.SplitMode.C

    story_parsed = []
    definitions = {}
    for paragraph in story["story"]:
        result = tokenizer_obj.tokenize(paragraph, mode)

        p = []
        for m in result:
            p.append({
                'word': m.surface(),
                'normalized': m.normalized_form()
            })
        story_parsed.append(p)


    return render_template('story.html', title=story['title'], paragraphs=story_parsed, dictionary=definitions)


@app.route("/account", methods=["GET", "POST"])
@login_required
def account_page():
    user_info = db.execute('SELECT * FROM users WHERE id = ?', session['user_id'])[0]

    if request.method == 'POST':

        new_username = request.form.get('new_username')
        new_password = request.form.get('new_password')
        confirm_new_password = request.form.get('new_password_confirmation')
        current_password = request.form.get('current_password')

        if not check_password_hash(user_info["hash"], current_password):
            flash('Incorrect CURRENT password.', "danger")
            return redirect(request.path)

        updates = []

        if new_username:
            if db.execute("SELECT username FROM users WHERE username=?", new_username):
                flash("That username already exists.", "danger")
                return redirect(request.path)

            db.execute('UPDATE users SET username = ? WHERE id = ?', new_username, session['user_id'])
            updates.append('username')

        if new_password:
            if new_password != confirm_new_password:
                flash('New password does not match confirmation', "danger")
                return redirect(request.path)

            db.execute('UPDATE users SET hash = ? WHERE id = ?', generate_password_hash(new_password), session["user_id"])
            updates.append('password')

        if len(updates):
            update = 'Successfully updated: ' + ', '.join(updates)
            update_category = "primary"
        else:
            update = "You didn't make any changes..."
            update_category = "danger"

        flash(update, update_category)
        return redirect("/account")

    return render_template('account.html', username=user_info['username'])


@app.route("/my_words")
@login_required
def my_words():
    return render_template('mywords.html')


@app.route('/_get_definition')
def get_definition():
    word = request.args.get('word')
    """Look up definition of word using jisho api."""

    # Contact API
    try:
        url = f"https://jisho.org/api/v1/search/words?keyword={word}"
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException:
        return ''

    # Parse response
    try:

        results = response.json()
        results = results['data']

        if len(results) > 0:
            return {
                "japanese": results[0]['japanese'],
                "english": results[0]['senses'][0]['english_definitions'],
                "part_of_speech": results[0]['senses'][0]["parts_of_speech"]
            }
        else: return ''
    except (KeyError, TypeError, ValueError):
        return ''


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return render_template('error.html', error=e)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)

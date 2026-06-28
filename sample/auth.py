# sample/auth.py — intentionally sloppy, so the crew has something to find
def login(users, name, password):
    for u in users:
        if u["name"] == name and u["password"] == password:
            return u
    # no return if not found -> implicit None, no logging, plaintext passwords

"""Small server-side form validation helper."""
import re
from datetime import date

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{2,20}$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Form:
    """Collects cleaned values and per-field errors.

    values -> what to re-display in the form, errors -> {field: message}.
    """

    def __init__(self, data=None, prefill=None):
        self.data = data if data is not None else {}
        self.values = dict(prefill or {})
        self.errors = {}

    @property
    def ok(self):
        return not self.errors

    def error(self, name, message):
        self.errors.setdefault(name, message)

    def first_error(self):
        return next(iter(self.errors.values()), "")

    def _get(self, name, keep=True):
        raw = self.data.get(name)
        raw = "" if raw is None else str(raw).strip()
        if keep:
            self.values[name] = raw
        return raw

    # -- field types -------------------------------------------------------
    def text(self, name, label, *, required=True, min_len=1, max_len=200, regex=None, message=None):
        v = self._get(name)
        if not v:
            if required:
                self.error(name, f"{label} is required.")
            return ""
        if _CTRL.search(v):
            self.error(name, f"{label} contains invalid characters.")
        elif len(v) < min_len:
            self.error(name, f"{label} must be at least {min_len} characters.")
        elif len(v) > max_len:
            self.error(name, f"{label} must be at most {max_len} characters.")
        elif regex is not None and not regex.fullmatch(v):
            self.error(name, message or f"{label} is not valid.")
        return v

    def email(self, name="email", label="Email"):
        return self.text(name, label, max_len=120, regex=EMAIL_RE, message="Enter a valid email address.").lower()

    def date(self, name, label, *, required=True, min_date=None, max_date=None):
        v = self._get(name)
        if not v:
            if required:
                self.error(name, f"{label} is required.")
            return None
        try:
            d = date.fromisoformat(v)
        except ValueError:
            self.error(name, f"{label} must be a valid date (YYYY-MM-DD).")
            return None
        if min_date and d < min_date:
            self.error(name, f"{label} cannot be before {min_date.isoformat()}.")
        elif max_date and d > max_date:
            self.error(name, f"{label} cannot be after {max_date.isoformat()}.")
        return d

    def choice(self, name, label, allowed, *, required=True):
        v = self._get(name)
        if not v and not required:
            return ""
        if v not in allowed:
            self.error(name, f"Choose a valid {label.lower()}.")
            return ""
        return v

    def ref(self, name, label, valid_ids, *, required=False):
        """A foreign-key select: value must be one of valid_ids (ints)."""
        v = self._get(name)
        if not v:
            if required:
                self.error(name, f"{label} is required.")
            return None
        if not v.isdigit() or int(v) not in valid_ids:
            self.error(name, f"Choose a valid {label.lower()}.")
            return None
        return int(v)

    def number(self, name, label, *, minimum=None, maximum=None, required=True):
        v = self._get(name)
        if not v:
            if required:
                self.error(name, f"{label} is required.")
            return None
        try:
            n = float(v)
            if n != n or n in (float("inf"), float("-inf")):
                raise ValueError
        except ValueError:
            self.error(name, f"{label} must be a number.")
            return None
        if minimum is not None and n < minimum:
            self.error(name, f"{label} must be at least {minimum:g}.")
        elif maximum is not None and n > maximum:
            self.error(name, f"{label} must be at most {maximum:g}.")
        return n

    def password(self, name="password", label="Password", *, required=True):
        v = self._get(name, keep=False)  # never echo passwords back
        if not v:
            if required:
                self.error(name, f"{label} is required.")
            return ""
        if len(v) < 8 or len(v) > 128:
            self.error(name, f"{label} must be 8-128 characters.")
        elif not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            self.error(name, f"{label} must contain at least one letter and one number.")
        return v

    def checkbox(self, name):
        v = 1 if self.data.get(name) else 0
        self.values[name] = v
        return v

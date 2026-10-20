# GarageLog

Vehicle service management and maintenance reminder platform for independent workshops (Django).

## Setup

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py seed_demo_users
```

### macOS / Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo_users
```

## Run

Start the development server with `python manage.py runserver`, then open http://127.0.0.1:8000/.

Run the tests with `pytest`.

Emails (verification links, password resets) are printed in the terminal running the server, because the development email backend is the console.

## Demo users (development only)

`python manage.py seed_demo_users` creates these users, all with the password `GarageLog-demo-1`. It refuses to run when `DEBUG` is off.

| Username | Role |
| --- | --- |
| admin | Admin (also a Django superuser) |
| mechanic1, mechanic2 | Mechanic |
| customer1, customer2 | Customer |

## Accounts and roles

| URL | What it does |
| --- | --- |
| `/accounts/signup/` | Customer signup, then a verification link is emailed |
| `/accounts/login/` | Log in with username or email |
| `/accounts/profile/` | View and edit your own profile |
| `/accounts/password-reset/` | Reset a forgotten password |
| `/dashboard/` | Redirects to your role's dashboard |

New signups are always customers and must verify their email before logging in. To restrict a view to a role, use the mixins in `accounts/mixins.py`:

```python
from accounts.mixins import MechanicRequiredMixin

class MyJobsView(MechanicRequiredMixin, ListView):
    ...
```

Logged-out users are sent to the login page; users with the wrong role get the 403 page. Create real mechanics and admins in the Django admin (`/admin/`) or with `createsuperuser` (which makes an Admin).

## Git workflow

- Every pull request needs one review and a passing CI run (`.github/workflows/ci.yml`).
- Use conventional commit messages, for example `feat: add vehicle list view`.

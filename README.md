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

## Vehicles and bookings

| URL | Who | What it does |
| --- | --- | --- |
| `/vehicles/` | Customer, Admin | Customers see their own vehicles; admins see all |
| `/vehicles/add/` | Customer, Admin | Add a vehicle (number plate, make, model, year, WoF and registration expiry) |
| `/vehicles/<id>/` | Owner, Admin | Vehicle details and service history (its bookings, newest first) |
| `/bookings/` | Everyone | Customers see their own bookings, mechanics the ones assigned to them, admins all (filter by status) |
| `/bookings/create/` | Customer, Admin | Book a service for one of your vehicles. Admins book for a customer and can assign a mechanic |
| `/bookings/<id>/edit/` | Owner until it starts, Admin | Change a booking. Admins also set the mechanic and status |
| `/bookings/<id>/cancel/` | Owner until it starts, Admin | Cancel a booking (it is kept for the history) |
| `/bookings/<id>/delete/` | Admin | Permanently delete a booking |

Someone else's vehicle or booking returns a 404, and a page your role can't use returns the 403 page.

### Booking rules

The rules live in one file, `bookings/scheduling.py`, so they are easy to change:

- Bookings are fixed 60-minute slots on the hour, Monday to Friday, 8:00 am to 5:00 pm (last start 4:00 pm).
- A slot can hold one booking per active mechanic (at least one). Pending and confirmed bookings use up a slot; cancelled and completed ones don't.
- The same vehicle can't have two active bookings at the same time, and a mechanic can't be assigned to two at the same time.
- Past dates and times earlier today are refused.
- Database constraints on `Booking` back these rules up, so a double booking is refused even if two requests arrive together.
- A vehicle that has bookings can't be deleted, so its service history is never lost.

## Git workflow

- Every pull request needs one review and a passing CI run (`.github/workflows/ci.yml`).
- Use conventional commit messages, for example `feat: add vehicle list view`.

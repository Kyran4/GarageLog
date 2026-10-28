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
python manage.py import_parts
python manage.py seed_demo_stock
```

### macOS / Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo_users
python manage.py import_parts
python manage.py seed_demo_stock
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
| mechanic1 | Mechanic at Auckland Central Workshop |
| mechanic2 | Mechanic at North Shore Workshop |
| customer1, customer2 | Customer (each with a demo vehicle) |

The command also creates the two demo workshops.

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
| `/vehicles/` | Everyone | Customers see their own vehicles. Mechanics search any vehicle in the system by number plate. Admins see all |
| `/vehicles/add/` | Customer, Admin | Add a vehicle (number plate, make, model, year, WoF and registration expiry) |
| `/vehicles/<id>/` | Owner, Mechanic, Admin | Vehicle details and service history across all workshops. Mechanics get read-only access |
| `/bookings/` | Everyone | Customers see their own bookings, mechanics every booking at their workshop, admins all (staff can filter by status) |
| `/bookings/create/` | Everyone | Customers choose a workshop and book one of their vehicles. Mechanics and admins book for a customer and can assign a mechanic. A mechanic's bookings are always at their own workshop |
| `/bookings/<id>/edit/` | Owner until it starts, workshop staff, Admin | Change a booking. Staff can also set the mechanic and status |
| `/bookings/<id>/cancel/` | Owner until it starts, workshop staff, Admin | Cancel a booking (it is kept for the history) |
| `/bookings/<id>/delete/` | Admin | Permanently delete a booking |

Someone else's booking (or, for customers, vehicle) returns a 404, and a page your role can't use returns the 403 page.

### Booking rules

The slot rules live in `bookings/scheduling.py` and each workshop's hours are on its record:

- Bookings are fixed 60-minute slots on the hour (`SLOT_MINUTES`). Each workshop sets its own opening and closing time and whether it opens on Saturday or Sunday; Monday to Friday are always open.
- A workshop's slot can hold one booking per active mechanic at that workshop (at least one). Pending and confirmed bookings use up a slot; cancelled and completed ones don't.
- The same vehicle can't have two active bookings at the same time (even at different workshops), and a mechanic can't be assigned to two at the same time or to another workshop's booking.
- Past dates and times earlier today are refused.
- Database constraints on `Booking` back these rules up, so a double booking is refused even if two requests arrive together.
- A vehicle that has bookings can't be deleted, so its service history is never lost.

## Workshops

GarageLog supports several workshops. Add and edit them in the Django admin (`/admin/`, "Workshops"): name, address, phone, opening hours, weekend opening, and whether the workshop is active.

- **Mechanics belong to one workshop.** Set it on the user in the Django admin. A mechanic must have a workshop, and can only see, make and change bookings for that workshop.
- **Customers choose a workshop** when they book. Inactive workshops can't be chosen.
- **Mechanics can look up any vehicle** in GarageLog by number plate and read its service history (across all workshops). Customer contact details are shown only once that customer has booked at the mechanic's workshop.
- **Admins** work across every workshop.

## Parts library

Parts live in one shared catalogue (`Part`), and each workshop keeps its own stock of them (`StockItem`: quantity, reorder level, optional workshop price, bin location). Mechanics and admins use it; customers don't.

| URL | What it does |
| --- | --- |
| `/parts/` | Find parts by number plate (a vehicle already in GarageLog), or by make, model and year, and/or by name, category and "in stock". Parts made for the vehicle are listed first, then universal parts. Each result shows the workshop's stock |
| `/parts/<id>/` | A part's fitment list and stock. Mechanics see their own workshop's stock; admins see every workshop's |
| `/parts/stock/` | Your workshop's stock, with filters and a low-stock view. Admins choose the workshop |
| `/parts/stock/add/` | Add a catalogue part to the workshop's stock. Edit and remove are on the stock list |

A mechanic can only change their own workshop's stock. Add or edit catalogue parts and their fitment in the Django admin (`/admin/`, "Parts").

### The demo catalogue

`python manage.py import_parts` loads `inventory/data/demo_parts.csv`: 200 generic parts (40 universal ones such as oil, wiper blades and bulbs, plus oil filters, air filters, front brake pads and spark plugs or fuel filters for 40 popular NZ vehicle ranges). **It is demo data: the part numbers and prices are made up and the fitment is illustrative, not checked against real vehicles.** Running it again updates parts instead of duplicating them. `python manage.py seed_demo_stock` then gives each workshop stock of about three quarters of the parts.

To add more parts, add rows to the CSV (or make your own file) and run `python manage.py import_parts path/to/file.csv`. Columns: `part_number, name, brand, category, default_price, universal, fitment, description`.

- `category` is one of `FLUIDS, FILTERS, BRAKES, IGNITION, ELECTRICAL, WIPERS, WORKSHOP`.
- `universal` is `yes` for parts that fit any vehicle (no fitment), otherwise `no`.
- `fitment` lists what a part fits, separated by semicolons, as `Make|Model|Years`. A model of `*` (or none) means every model of that make, and years are optional: `2007-2018`, `2010-` or `-2012`. For example `Toyota|Corolla|2007-2018;Toyota|Yaris;Mazda|*`.
- If any row has a problem, nothing is imported and the command lists the lines to fix.

For real part numbers and fitment you would need licensed catalogue data (TecDoc is the industry standard) or an export from a workshop's own system, so the library is designed to take a CSV.

## Git workflow

- Every pull request needs one review and a passing CI run (`.github/workflows/ci.yml`).
- Use conventional commit messages, for example `feat: add vehicle list view`.

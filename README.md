# GarageLog

GarageLog is a Django-based vehicle service management app for independent workshops. It brings customer bookings, workshop scheduling, vehicle service histories, job cards, parts inventory, and invoices into one place.

## Features

- Customer, mechanic, and admin roles with role- and workshop-scoped access.
- Vehicle registration with WoF and registration expiry reminders.
- Workshop-aware appointment booking, capacity checks, and booking status updates.
- Job cards with an optional handover checklist, parts usage, and customer invoices.
- Shared parts catalogue, workshop stock, low-stock indicators, and warehouse orders.
- Dashboards, analytics, in-app customer updates, and printable service summaries.

The demo parts catalogue and fitments are illustrative only. Do not rely on them for real vehicle compatibility, safety, pricing, or stock decisions.

## Setup

Requires Python 3.12 or later.

### Windows PowerShell

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py seed_demo_users
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
python manage.py seed_demo_stock
```

The demo-user command creates accounts using the publicly documented development password below. Use these only on a local development database; never deploy or expose a site populated with demo users.

## Run

Start the development server with `python manage.py runserver`, then open http://127.0.0.1:8000/.

Run checks and tests with:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
pytest
```

## Email behavior

Booking status changes are shown to customers as in-app updates; no email service is needed for that workflow. Password-reset emails use a development backend that prints the message in the server terminal. Signup does not send email or require verification; new accounts are active customers immediately.

An optional Gmail API backend is available for password resets. It requires separately configured Google OAuth credentials and is not enabled by default. Never put OAuth credentials in this repository; configure them as private environment variables on the host.

## Deployment and secrets

This repository is a development project, not a production-ready deployment recipe. Before running it on a public host:

- Set `DEBUG=False`.
- Set a new, high-entropy `SECRET_KEY`; do not use the example value. Generate one with `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` and store it only in the host's secret environment settings.
- Set `ALLOWED_HOSTS` to the exact hostnames serving the app.
- Configure a production database with `DATABASE_URL`, HTTPS, secure cookie settings, backups, and a production email backend if password resets must be delivered.
- Do not run `seed_demo_users` or expose demo accounts on a public deployment.
- Review Django's deployment checklist and run `python manage.py check --deploy` against the deployment configuration.

Settings reject a missing/example secret key or missing `ALLOWED_HOSTS` when `DEBUG` is off. `.env` files, local databases, logs, uploads, and collected static files are ignored by Git; `.env.example` contains placeholders only. Keep real credentials in your hosting provider's secret environment settings.

## Demo users (development only)

`python manage.py seed_demo_users` creates these users, all with the publicly known development password `GarageLog-demo-1`. The command refuses to run when `DEBUG` is off. This is demo-only data; do not reuse the password for any real account.

| Username | Role |
| --- | --- |
| admin | Admin (also a Django superuser) |
| mechanic1 | Mechanic at Auckland Central Workshop |
| mechanic2 | Mechanic at North Shore Workshop |
| warehouse1 | Staff (mechanic role) at the Parts Warehouse |
| customer1, customer2 | Customer (each with a demo vehicle) |

The command also creates the two demo workshops and the parts warehouse.

To create only the demo locations without adding demo accounts, run:

```sh
python manage.py seed_demo_workshops
```

Then run `python manage.py seed_demo_stock` to import the illustrative demo parts catalogue if it is empty and add sample stock to each location. These parts and quantities are for demonstration, not verified real inventory.

## Accounts and roles

| URL | What it does |
| --- | --- |
| `/accounts/signup/` | Customer signup; accounts are active immediately |
| `/accounts/login/` | Log in with username or email |
| `/accounts/profile/` | View and edit your own profile |
| `/accounts/password-reset/` | Reset a forgotten password |
| `/dashboard/` | Redirects to your role's dashboard |
| `/updates/` | Review in-app booking status updates and mark them as read |

New signups are always active customers. An admin can change a user's role and assign their workshop in Django admin (`/admin/`, "Users"). Mechanics must be assigned to a workshop. To restrict a view to a role, use the mixins in `accounts/mixins.py`:

```python
from accounts.mixins import MechanicRequiredMixin

class MyJobsView(MechanicRequiredMixin, ListView):
    ...
```

Logged-out users are sent to the login page; users with the wrong role get the 403 page. Create real mechanics and admins in the Django admin (`/admin/`) or with `createsuperuser` (which makes an Admin).

Booking status changes create in-app updates for the customer. They appear in the navigation and on `/updates/`; this does not require an email sender.

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

### Job cards and handover checklist

Mechanics update job cards for their assigned work; admins can manage all job cards. The job-card form includes an optional, collapsible pre-handover checklist. Each check can be marked **Done** or **Not applicable**, or left **Not checked**, with an optional note for follow-up. The checklist is a workshop aid, not a formal inspection or certification.

### Booking rules

The slot rules live in `bookings/scheduling.py` and each workshop's hours are on its record:

- Bookings are fixed 60-minute slots on the hour (`SLOT_MINUTES`). Each workshop sets its own opening and closing time and whether it opens on Saturday or Sunday; Monday to Friday are always open.
- A workshop's slot can hold one booking per active mechanic at that workshop (at least one). Pending and confirmed bookings use up a slot; cancelled and completed ones don't.
- The same vehicle can't have two active bookings at the same time (even at different workshops), and a mechanic can't be assigned to two at the same time or to another workshop's booking.
- Past dates and times earlier today are refused.
- Database constraints on `Booking` back these rules up, so a double booking is refused even if two requests arrive together.
- A vehicle that has bookings can't be deleted, so its service history is never lost.
- Customers can open a print-friendly service summary from completed entries in a vehicle's service history. The summary includes the invoice and any recorded job-card handover checks.

The customer dashboard highlights WoF and registration dates that are due soon or expired. Vehicle owners can update dates from the vehicle page; missing dates are called out there so they can be added.

### Dashboard attention

The staff dashboards highlight pending bookings, overdue incomplete job cards, and low stock. Mechanics only see overdue job cards assigned to them and low-stock items at their own workshop; admins can follow low-stock links for each location.

## Workshops

GarageLog supports several workshops. Add and edit them in the Django admin (`/admin/`, "Workshops"): name, address, phone, opening hours, weekend opening, and whether the workshop is active.

- **Mechanics belong to one workshop.** Set it on the user in the Django admin. A mechanic must have a workshop, and can only see, make and change bookings for that workshop.
- **Customers choose a workshop** when they book. Inactive workshops can't be chosen.
- **Mechanics can look up any vehicle** in GarageLog by number plate and read its service history (across all workshops). Customer contact details are shown only once that customer has booked at the mechanic's workshop.
- **Admins** work across every workshop.

### The parts warehouse

One location can be marked as the **parts warehouse** (tick "Parts warehouse" on it in the Django admin; only one location can be). It is the central store that supplies the workshops:

- It holds parts stock but **does not take customer bookings**, so it never appears in the workshop list when booking, and nobody can book there.
- Staff who work there (a mechanic-role user whose workshop is the warehouse) manage its stock and see a stock-focused dashboard with no bookings.
- Every workshop's mechanics can see what the warehouse holds, read-only, next to their own stock in the parts search and on a part's page, so they know what can be supplied. Only warehouse staff and admins can change the warehouse's stock.
- Admins see the warehouse listed separately on their dashboard, with a link to its stock.

If a location was already called a warehouse when you updated (for example "Main Workshop" renamed to "Parts Warehouse"), the update marks it automatically, but only when exactly one location's name contains "warehouse". Otherwise tick the box yourself. Any old bookings or mechanics still attached to it need moving to a real workshop. Admins can reassign a booking by editing it, and a booking that is already cancelled or completed can stay where it is.

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

`inventory/data/demo_parts.csv` holds 200 generic parts (40 universal ones such as oil, wiper blades and bulbs, plus oil filters, air filters, front brake pads and spark plugs or fuel filters for 40 popular NZ vehicle ranges). **It is demo data: the part numbers and prices are made up and the fitment is illustrative, not checked against real vehicles.**

### Seeding a workshop's stock

Stocking a workshop is done once, from the terminal:

```
python manage.py seed_demo_stock
```

This loads the demo catalogue if the parts library is empty, then gives every location a starting stock from it. Workshops get about three quarters of the parts with sample quantities, and the parts warehouse gets **every** part in large quantities (20 to 150). It only adds parts a location doesn't have yet and never changes existing stock, so it is safe to run again.

- `--workshop "Workshop name"` stocks just that workshop or the warehouse. Repeat it for more than one. Use it after adding a new workshop.
- `--empty` lists every part at a quantity of 0 instead of sample or warehouse quantities, ready for real counts to be entered.

After that, each workshop adds, edits and removes its own stock on the Parts pages.

To add more parts to the library, add rows to the CSV (or make your own file) and run `python manage.py import_parts path/to/file.csv` (with no path it imports the demo catalogue). Then seed workshops as above to pick up the new parts. Columns: `part_number, name, brand, category, default_price, universal, fitment, description`.

- `category` is one of `FLUIDS, FILTERS, BRAKES, IGNITION, ELECTRICAL, WIPERS, WORKSHOP`.
- `universal` is `yes` for parts that fit any vehicle (no fitment), otherwise `no`.
- `fitment` lists what a part fits, separated by semicolons, as `Make|Model|Years`. A model of `*` (or none) means every model of that make, and years are optional: `2007-2018`, `2010-` or `-2012`. For example `Toyota|Corolla|2007-2018;Toyota|Yaris;Mazda|*`.
- If any row has a problem, nothing is imported and the command lists the lines to fix.

For real part numbers and fitment you would need licensed catalogue data (TecDoc is the industry standard) or an export from a workshop's own system, so the library is designed to take a CSV.

## License

No license has been selected for this repository yet. Until a license is added, public visibility does not grant permission to reuse, modify, or distribute the source.

## Git workflow

- Every pull request needs one review and a passing CI run (`.github/workflows/ci.yml`).
- Use conventional commit messages, for example `feat: add vehicle list view`.

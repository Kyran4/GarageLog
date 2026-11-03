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

## Run

Start the development server with `python manage.py runserver`, then open http://127.0.0.1:8000/.

Run the tests with `pytest`.

Password-reset emails are printed in the terminal running the server, because the development email backend is the console. Signup does not send email; new accounts need admin approval before they can log in.

### Optional production email for password resets

The default email backend is for local development and prints password-reset messages to the console. To deliver password-reset emails from Render's free web service, which cannot use SMTP ports, configure the Gmail API and OAuth 2.0 credentials; this does not use your Gmail password. Email is not needed for signup or admin approval.

In Google Cloud Console, create a project, enable the Gmail API, configure the OAuth consent screen, and create an OAuth client ID. Authorize the app for the `https://www.googleapis.com/auth/gmail.send` scope and obtain an OAuth refresh token for the Gmail account that will send the messages. Keep the OAuth client secret and refresh token private. Google classifies this as a sensitive scope; an app left in External testing can have refresh tokens that expire after seven days.

Add these environment variables to the Render web service:

| Variable | Value |
| --- | --- |
| `EMAIL_BACKEND` | `accounts.gmail_email.GmailEmailBackend` |
| `DEFAULT_FROM_EMAIL` | `GarageLog <your-gmail-address@gmail.com>` |
| `GMAIL_CLIENT_ID` | OAuth client ID from Google Cloud |
| `GMAIL_CLIENT_SECRET` | OAuth client secret |
| `GMAIL_REFRESH_TOKEN` | Refresh token authorized for `gmail.send` |
| `GMAIL_API_TIMEOUT` | `10` (optional; request timeout in seconds) |

Set the From address to the same Gmail account you authorized. Store all credentials only in Render's environment variables, never in source control. Save the variables and redeploy or restart the web service. Locally, the console backend remains active unless `EMAIL_BACKEND` is set.

## Demo users (development only)

`python manage.py seed_demo_users` creates these users, all with the password `GarageLog-demo-1`. It refuses to run when `DEBUG` is off.

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
| `/accounts/signup/` | Customer signup; an admin must approve the account before login |
| `/accounts/login/` | Log in with username or email |
| `/accounts/profile/` | View and edit your own profile |
| `/accounts/password-reset/` | Reset a forgotten password |
| `/dashboard/` | Redirects to your role's dashboard |

New signups are always customers and must be approved by an admin before logging in. In Django admin (`/admin/`), select pending users and choose **Approve selected users and activate their accounts**, or edit an individual user and enable **Is approved**. To restrict a view to a role, use the mixins in `accounts/mixins.py`:

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

## Git workflow

- Every pull request needs one review and a passing CI run (`.github/workflows/ci.yml`).
- Use conventional commit messages, for example `feat: add vehicle list view`.

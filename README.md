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

## How it works

GarageLog brings the main workshop workflows together:

- **Customers** maintain vehicle details, book service appointments, and review booking updates and service history.
- **Mechanics** manage work assigned to them, record job-card details, and check parts available at their workshop or the warehouse.
- **Admins** oversee users, bookings, workshops, job cards, and inventory across locations.

Workshops have their own opening hours, appointment capacity, mechanics, and stock. A separate parts warehouse can supply parts to those workshops without taking customer bookings.

Booking updates appear in the app. New customer accounts are active immediately, and password-reset email delivery depends on the email service configured for the installation.

## Accounts and roles

| URL | What it does |
| --- | --- |
| `/accounts/signup/` | Customer signup; accounts are active immediately |
| `/accounts/login/` | Log in with username or email |
| `/accounts/profile/` | View and edit your own profile |
| `/accounts/password-reset/` | Reset a forgotten password |
| `/dashboard/` | Redirects to your role's dashboard |
| `/updates/` | Review in-app booking status updates and mark them as read |

Logged-out users are sent to the login page; users with the wrong role are shown an access-denied page. Mechanics have access to their assigned workshop, while admins can work across all workshops.

Booking status changes appear as in-app updates in the navigation and on `/updates/`.

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

Customers can only view their own vehicles and bookings. Access is limited according to each person's role and workshop.

### Job cards and handover checklist

Mechanics update job cards for their assigned work; admins can manage all job cards. The job-card form includes an optional, collapsible pre-handover checklist. Each check can be marked **Done** or **Not applicable**, or left **Not checked**, with an optional note for follow-up. The checklist is a workshop aid, not a formal inspection or certification.

### Booking rules

- Appointments are fixed one-hour slots within each workshop's opening hours. Available capacity reflects the active mechanics at that workshop.
- A vehicle and a mechanic can't be double-booked. Customers can't book in the past, and cancelled or completed appointments no longer use a slot.
- Vehicle service history is retained alongside bookings. Completed services can be viewed as print-friendly summaries with invoices and recorded handover checks.
- Customer dashboards highlight WoF and registration dates that are due soon or expired.

### Dashboard attention

The staff dashboards highlight pending bookings, overdue incomplete job cards, and low stock. Mechanics only see overdue job cards assigned to them and low-stock items at their own workshop; admins can follow low-stock links for each location.

## Workshops

GarageLog supports several workshops, each with its own contact details, opening hours, weekend availability, and active status.

- **Mechanics belong to one workshop** and manage its bookings and stock.
- **Customers choose a workshop** when they book. Inactive workshops can't be chosen.
- **Mechanics can look up any vehicle** in GarageLog by number plate and read its service history (across all workshops). Customer contact details are shown only once that customer has booked at the mechanic's workshop.
- **Admins** work across every workshop.

### The parts warehouse

The optional **parts warehouse** is the central store that supplies workshops:

- It holds parts stock but **does not take customer bookings**, so it never appears in the workshop list when booking, and nobody can book there.
- Warehouse staff manage its stock and see a stock-focused dashboard with no bookings.
- Every workshop's mechanics can see what the warehouse holds, read-only, next to their own stock in the parts search and on a part's page, so they know what can be supplied. Only warehouse staff and admins can change the warehouse's stock.
- Admins see the warehouse listed separately on their dashboard, with a link to its stock.

## Parts library

Parts live in one shared catalogue (`Part`), and each workshop keeps its own stock of them (`StockItem`: quantity, reorder level, optional workshop price, bin location). Mechanics and admins use it; customers don't.

| URL | What it does |
| --- | --- |
| `/parts/` | Find parts by number plate (a vehicle already in GarageLog), or by make, model and year, and/or by name, category and "in stock". Parts made for the vehicle are listed first, then universal parts. Each result shows the workshop's stock |
| `/parts/<id>/` | A part's fitment list and stock. Mechanics see their own workshop's stock; admins see every workshop's |
| `/parts/stock/` | Your workshop's stock, with filters and a low-stock view. Admins choose the workshop |
| `/parts/stock/add/` | Add a catalogue part to the workshop's stock. Edit and remove are on the stock list |

A mechanic can only change their own workshop's stock. Parts can be searched by vehicle or by catalogue details, with vehicle-specific matches shown before universal parts.

### The demo catalogue

The included catalogue and fitments are illustrative demo data. Part numbers, prices, and vehicle compatibility have not been verified and should not be used for real-world purchasing or safety decisions.

from django.contrib import messages
from django.db.models import F, Q
from django.http import QueryDict
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.mixins import RoleRequiredMixin
from accounts.models import User
from workshops.models import Workshop

from .forms import PartSearchForm, StockItemForm
from .models import Part, PartFitment, StockItem, parts_matching


class StaffOnlyMixin(RoleRequiredMixin):
    """The parts library is for workshop staff. Customers have no access."""

    allowed_roles = (User.Role.MECHANIC, User.Role.ADMIN)


class WorkshopScopeMixin:
    """Works out which workshop's stock a page is about.

    A mechanic always works with their own workshop. An admin picks one with ?workshop=<id>
    and otherwise gets the first workshop.
    """

    def get_workshop(self):
        if not hasattr(self, '_workshop'):
            user = self.request.user
            if user.is_mechanic:
                self._workshop = user.workshop
            else:
                chosen = self.request.GET.get('workshop', '')
                workshops = Workshop.objects.order_by('name')
                workshop = workshops.filter(pk=chosen).first() if chosen.isdigit() else None
                self._workshop = workshop or workshops.first()
        return self._workshop

    def workshop_query(self):
        """'?workshop=3' for admins, so links keep the workshop they are looking at."""
        workshop = self.get_workshop()
        if self.request.user.is_admin_role and workshop:
            return f'?workshop={workshop.pk}'
        return ''


# ---------------------------------------------------------------- finding parts


class PartSearchView(StaffOnlyMixin, WorkshopScopeMixin, ListView):
    template_name = 'inventory/part_search.html'
    context_object_name = 'parts'
    paginate_by = 25

    def get_form(self):
        if not hasattr(self, '_form'):
            self._form = PartSearchForm(self.request.GET or None, user=self.request.user)
        return self._form

    def get_queryset(self):
        form = self.get_form()
        parts = Part.objects.filter(is_active=True)
        if form.is_bound:
            if not form.is_valid():
                return Part.objects.none()
            data = form.cleaned_data
            vehicle = form.vehicle
            if vehicle:  # a plate in GarageLog: use that vehicle's make, model and year
                parts = parts_matching(vehicle.make, vehicle.model, vehicle.year, parts)
            else:
                parts = parts_matching(data['make'], data['model'], data['year'], parts)
            if data['q']:
                parts = parts.filter(
                    Q(name__icontains=data['q']) | Q(part_number__icontains=data['q']) | Q(brand__icontains=data['q'])
                )
            if data['category']:
                parts = parts.filter(category=data['category'])
            if data['in_stock']:
                workshop = self.get_workshop()
                parts = parts.filter(stock_items__workshop=workshop, stock_items__quantity__gt=0).distinct() \
                    if workshop else parts.none()
        # Parts made for the vehicle come before universal ones.
        return parts.order_by('universal', 'category', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = self.get_form()
        workshop = self.get_workshop()

        parts = list(context['parts'])
        stock = {}
        if workshop:
            stock = {
                item.part_id: item
                for item in StockItem.objects.filter(workshop=workshop, part__in=parts)
            }
        for part in parts:
            part.workshop_stock = stock.get(part.pk)
        context['parts'] = parts

        # What the parts warehouse holds, shown beside the workshop's own stock (read-only).
        warehouse = Workshop.get_warehouse()
        if warehouse is not None and warehouse == workshop:
            warehouse = None  # the warehouse's own staff already see its stock in the main column
        if warehouse is not None:
            held = {
                item.part_id: item
                for item in StockItem.objects.filter(workshop=warehouse, part__in=parts)
            }
            for part in parts:
                part.warehouse_stock = held.get(part.pk)
        context['warehouse'] = warehouse

        query = QueryDict(mutable=True)
        query.update({key: value for key, value in self.request.GET.items() if key != 'page' and value})
        context.update({
            'form': form,
            'workshop': workshop,
            'vehicle': form.vehicle if form.is_bound and form.is_valid() else None,
            'searched': form.is_bound,
            'querystring': query.urlencode(),
            'makes': PartFitment.objects.order_by('make').values_list('make', flat=True).distinct(),
            'models': PartFitment.objects.exclude(model='').order_by('model').values_list('model', flat=True).distinct(),
            'workshop_query': self.workshop_query(),
        })
        return context


class PartDetailView(StaffOnlyMixin, WorkshopScopeMixin, DetailView):
    template_name = 'inventory/part_detail.html'
    context_object_name = 'part'
    queryset = Part.objects.prefetch_related('fitments')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        stock = StockItem.objects.filter(part=self.object).select_related('workshop')
        if user.is_mechanic:
            # A mechanic sees their own workshop's stock, plus what the parts warehouse holds.
            stock = stock.filter(Q(workshop_id=user.workshop_id) | Q(workshop__is_parts_warehouse=True))
        rows = list(stock.order_by('workshop__name'))
        for item in rows:
            item.can_edit = user.is_admin_role or item.workshop_id == user.workshop_id
        context['stock_rows'] = rows
        context['workshop'] = self.get_workshop()
        context['already_stocked'] = (
            context['workshop'] is not None
            and StockItem.objects.filter(part=self.object, workshop=context['workshop']).exists()
        )
        context['workshop_query'] = self.workshop_query()
        return context


# ---------------------------------------------------------------- a workshop's stock


class StockListView(StaffOnlyMixin, WorkshopScopeMixin, ListView):
    template_name = 'inventory/stock_list.html'
    context_object_name = 'items'
    paginate_by = 30

    def get_queryset(self):
        workshop = self.get_workshop()
        if workshop is None:
            return StockItem.objects.none()
        items = StockItem.objects.filter(workshop=workshop).select_related('part')
        query = self.request.GET.get('q', '').strip()
        if query:
            items = items.filter(Q(part__name__icontains=query) | Q(part__part_number__icontains=query))
        category = self.request.GET.get('category', '')
        if category in Part.Category.values:
            items = items.filter(part__category=category)
        if self.request.GET.get('low'):
            items = items.filter(quantity__lte=F('reorder_level'))
        return items

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workshop = self.get_workshop()
        everything = StockItem.objects.filter(workshop=workshop) if workshop else StockItem.objects.none()
        query = QueryDict(mutable=True)
        query.update({key: value for key, value in self.request.GET.items() if key != 'page' and value})
        context.update({
            'workshop': workshop,
            'workshops': Workshop.objects.order_by('name') if self.request.user.is_admin_role else None,
            'total_count': everything.count(),
            'low_count': everything.filter(quantity__lte=F('reorder_level')).count(),
            'search_text': self.request.GET.get('q', '').strip(),
            'category': self.request.GET.get('category', ''),
            'low_only': bool(self.request.GET.get('low')),
            'categories': Part.Category.choices,
            'querystring': query.urlencode(),
            'workshop_query': self.workshop_query(),
        })
        return context


class StockQuerysetMixin(StaffOnlyMixin, WorkshopScopeMixin):
    def get_queryset(self):
        items = StockItem.objects.select_related('part', 'workshop')
        if self.request.user.is_mechanic:
            return items.filter(workshop_id=self.request.user.workshop_id)  # another workshop's stock is a 404
        return items

    def get_success_url(self):
        return reverse('inventory:stock') + self.workshop_query()


class StockCreateView(StaffOnlyMixin, WorkshopScopeMixin, CreateView):
    form_class = StockItemForm
    template_name = 'inventory/stock_form.html'

    def get(self, request, *args, **kwargs):
        if self.get_workshop() is None:
            messages.error(request, "You aren't assigned to a workshop yet, so there is no stock to add to.")
            return redirect('dashboard')
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.get_workshop() is None:
            return redirect('dashboard')
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['workshop'] = self.get_workshop()
        return kwargs

    def get_initial(self):
        initial = super().get_initial()
        part_id = self.request.GET.get('part', '')
        if part_id.isdigit():
            initial['part'] = part_id
        return initial

    def form_valid(self, form):
        form.instance.workshop = self.get_workshop()
        self.object = form.save()
        messages.success(self.request, f'{self.object.part.part_number} was added to {self.object.workshop.name} stock.')
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse('inventory:stock') + self.workshop_query()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['workshop'] = self.get_workshop()
        context['workshop_query'] = self.workshop_query()
        return context


class StockUpdateView(StockQuerysetMixin, UpdateView):
    form_class = StockItemForm
    template_name = 'inventory/stock_form.html'
    context_object_name = 'item'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['workshop'] = self.object.workshop
        return kwargs

    def get_workshop(self):
        return self.object.workshop if getattr(self, 'object', None) else super().get_workshop()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Stock updated for {self.object.part.part_number}.')
        return response

    def get_success_url(self):
        query = f'?workshop={self.object.workshop_id}' if self.request.user.is_admin_role else ''
        return reverse('inventory:stock') + query

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['workshop'] = self.object.workshop
        context['workshop_query'] = f'?workshop={self.object.workshop_id}' if self.request.user.is_admin_role else ''
        return context


class StockDeleteView(StockQuerysetMixin, DeleteView):
    template_name = 'inventory/stock_confirm_delete.html'
    context_object_name = 'item'

    def get_success_url(self):
        query = f'?workshop={self.object.workshop_id}' if self.request.user.is_admin_role else ''
        return reverse('inventory:stock') + query

    def form_valid(self, form):
        label = self.object.part.part_number
        response = super().form_valid(form)
        messages.success(self.request, f'{label} was removed from stock.')
        return response

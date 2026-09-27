
import django.contrib.postgres.constraints
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeRole',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True)),
                ('base_salary', models.DecimalField(decimal_places=2, max_digits=10)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Room',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.CharField(max_length=10, unique=True)),
                ('floor', models.PositiveSmallIntegerField(default=1)),
                ('size_sqft', models.PositiveIntegerField(default=250)),
                ('is_active', models.BooleanField(default=True, help_text='Inactive rooms are out of service and not bookable.')),
            ],
            options={
                'ordering': ['number'],
            },
        ),
        migrations.CreateModel(
            name='Booking',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('check_in', models.DateField()),
                ('check_out', models.DateField()),
                ('guests_count', models.PositiveSmallIntegerField(default=1)),
                ('status', models.CharField(choices=[('confirmed', 'Confirmed'), ('checked_in', 'Checked in'), ('checked_out', 'Checked out'), ('cancelled', 'Cancelled')], default='confirmed', max_length=12)),
                ('nightly_rate', models.DecimalField(decimal_places=2, max_digits=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('checked_in_at', models.DateTimeField(blank=True, null=True)),
                ('checked_out_at', models.DateTimeField(blank=True, null=True)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('guest', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bookings', to=settings.AUTH_USER_MODEL)),
                ('room', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bookings', to='hotel.room')),
            ],
            options={
                'ordering': ['-check_in', '-id'],
            },
        ),
        migrations.CreateModel(
            name='Bill',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nights', models.PositiveSmallIntegerField()),
                ('room_total', models.DecimalField(decimal_places=2, max_digits=12)),
                ('service_total', models.DecimalField(decimal_places=2, max_digits=12)),
                ('total', models.DecimalField(decimal_places=2, max_digits=12)),
                ('issued_at', models.DateTimeField(auto_now_add=True)),
                ('issued_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('booking', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='bill', to='hotel.booking')),
            ],
        ),
        migrations.CreateModel(
            name='Employee',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(max_length=100)),
                ('salary', models.DecimalField(decimal_places=2, max_digits=10)),
                ('hired_on', models.DateField()),
                ('user', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='employee', to=settings.AUTH_USER_MODEL)),
                ('role', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='employees', to='hotel.employeerole')),
            ],
            options={
                'ordering': ['full_name'],
            },
        ),
        migrations.CreateModel(
            name='Item',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, unique=True)),
                ('category', models.CharField(default='Food', max_length=40)),
                ('price', models.DecimalField(decimal_places=2, max_digits=8)),
                ('is_available', models.BooleanField(default=True)),
            ],
            options={
                'ordering': ['category', 'name'],
                'constraints': [models.CheckConstraint(condition=models.Q(('price__gt', 0)), name='item_price_positive')],
            },
        ),
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('guest', 'Guest'), ('staff', 'Staff'), ('admin', 'Admin')], default='guest', max_length=10)),
                ('phone', models.CharField(blank=True, max_length=30)),
                ('address', models.CharField(blank=True, max_length=200)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profile', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='RoomServiceOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('quantity', models.PositiveSmallIntegerField()),
                ('unit_price', models.DecimalField(decimal_places=2, max_digits=8)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('booking', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='room_service_orders', to='hotel.booking')),
                ('item', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='orders', to='hotel.item')),
                ('ordered_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['created_at', 'id'],
            },
        ),
        migrations.CreateModel(
            name='RoomType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, unique=True)),
                ('description', models.TextField(blank=True)),
                ('beds', models.PositiveSmallIntegerField(default=1)),
                ('capacity', models.PositiveSmallIntegerField(default=2)),
                ('air_conditioned', models.BooleanField(default=True)),
                ('nightly_rate', models.DecimalField(decimal_places=2, max_digits=10)),
            ],
            options={
                'ordering': ['nightly_rate', 'id'],
                'constraints': [models.CheckConstraint(condition=models.Q(('nightly_rate__gt', 0)), name='roomtype_rate_positive')],
            },
        ),
        migrations.AddField(
            model_name='room',
            name='room_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='rooms', to='hotel.roomtype'),
        ),
        migrations.CreateModel(
            name='AuditLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('command', models.CharField(max_length=40)),
                ('outcome', models.CharField(max_length=10)),
                ('detail', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('booking', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='audit', to='hotel.booking')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [models.Index(fields=['booking', 'created_at'], name='audit_booking')],
            },
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['room', 'check_in', 'check_out'], name='booking_room_dates'),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['guest', '-check_in'], name='booking_guest'),
        ),
        migrations.AddIndex(
            model_name='booking',
            index=models.Index(fields=['status', 'check_in'], name='booking_status_checkin'),
        ),
        migrations.AddConstraint(
            model_name='booking',
            constraint=models.CheckConstraint(condition=models.Q(('check_out__gt', models.F('check_in'))), name='booking_dates_ordered'),
        ),
        migrations.AddConstraint(
            model_name='booking',
            constraint=models.CheckConstraint(condition=models.Q(('guests_count__gte', 1)), name='booking_guests_positive'),
        ),
        migrations.AddConstraint(
            model_name='booking',
            constraint=django.contrib.postgres.constraints.ExclusionConstraint(condition=models.Q(('status__in', ['confirmed', 'checked_in'])), expressions=[(models.Func(models.F('room_id'), models.F('room_id'), models.Value('[]'), function='int8range'), '&&'), (models.Func(models.F('check_in'), models.F('check_out'), models.Value('[)'), function='daterange'), '&&')], name='booking_no_overlap', violation_error_message='Room is already booked for these dates.'),
        ),
        migrations.AddConstraint(
            model_name='roomserviceorder',
            constraint=models.CheckConstraint(condition=models.Q(('quantity__gte', 1)), name='order_quantity_positive'),
        ),
    ]

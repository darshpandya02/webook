import json

from django.core.management.base import BaseCommand

from hotel.seed import seed


class Command(BaseCommand):
    help = "Load or restore the demo data (demo users, rooms, menu, bookings relative to today)."

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(seed(reset=True), indent=2))

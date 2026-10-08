"""Copy legacy KYC files out of the general media store safely.

This command is deliberately dry-run by default.  Run it after migration 0027
and after provisioning the private KYC bucket.  It copies each legacy object,
updates the database only after the private copy exists, and can remove the
old object only when explicitly requested.
"""

from django.core.management.base import BaseCommand, CommandError
from django.core.files.storage import default_storage, storages

from handy.models import HandymanDocument, private_kyc_upload_path


class Command(BaseCommand):
    help = "Migrate legacy KYC files to the private KYC storage alias. Dry-run by default."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Perform the copy and database update.')
        parser.add_argument(
            '--delete-source',
            action='store_true',
            help='Delete the legacy object after a verified private copy (requires --apply).',
        )
        parser.add_argument('--limit', type=int, help='Process at most this many documents.')

    def handle(self, *args, **options):
        if options['delete_source'] and not options['apply']:
            raise CommandError('--delete-source requires --apply.')

        source_storage = default_storage
        destination_storage = storages['private_kyc']
        queryset = HandymanDocument.objects.exclude(file='').order_by('pk')
        if options['limit']:
            queryset = queryset[:options['limit']]

        migrated = skipped = missing = 0
        for document in queryset.iterator() if not options['limit'] else queryset:
            source_name = document.file.name
            if source_name.startswith('kyc/'):
                skipped += 1
                continue
            if not source_storage.exists(source_name):
                self.stderr.write(f'#{document.pk}: source missing: {source_name}')
                missing += 1
                continue

            destination_name = private_kyc_upload_path(document, source_name)
            if not options['apply']:
                self.stdout.write(f'DRY-RUN #{document.pk}: {source_name} -> {destination_name}')
                continue

            with source_storage.open(source_name, 'rb') as source_file:
                saved_name = destination_storage.save(destination_name, source_file)
            if not destination_storage.exists(saved_name):
                raise CommandError(f'#{document.pk}: private copy could not be verified.')

            document.file.name = saved_name
            document.save(update_fields=['file'])
            if options['delete_source']:
                source_storage.delete(source_name)
            migrated += 1
            self.stdout.write(self.style.SUCCESS(f'#{document.pk}: migrated to {saved_name}'))

        self.stdout.write(
            f'KYC migration complete: migrated={migrated}, skipped={skipped}, missing={missing}, '
            f'mode={"apply" if options["apply"] else "dry-run"}.'
        )

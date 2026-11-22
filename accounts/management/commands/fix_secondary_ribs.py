"""
Corrige les comptes secondaires (épargne) dont le code banque, le code guichet
ou le format diffèrent du compte primaire (courant) du même utilisateur.
Seul le numéro de compte est régénéré ; les autres composants sont copiés
depuis le compte primaire (clé et chiffres de contrôle recalculés).
"""
from django.core.management.base import BaseCommand
from accounts.models import BankAccount
from accounts.services import generate_rib_for_secondary
from accounts import rib_formats


class Command(BaseCommand):
    help = "Aligne les RIBs des comptes secondaires sur le compte primaire"

    def handle(self, *args, **options):
        fixed = 0
        for primary in BankAccount.objects.filter(is_primary=True).select_related('user', 'bank'):
            iso = primary.get_country_prefix()
            p_fields = rib_formats.split(iso, primary.rib)
            secondaries = BankAccount.objects.filter(
                user=primary.user, bank=primary.bank, is_primary=False
            )
            for sec in secondaries:
                if p_fields is None:
                    # Ancien format 27 caractères
                    coherent = (sec.rib[9:14] == primary.rib[9:14]
                                and sec.rib[25:27] == primary.rib[25:27]
                                and sec.rib[2:4] == primary.rib[2:4])
                else:
                    s_fields = rib_formats.split(iso, sec.rib)
                    coherent = s_fields is not None and all(
                        s_fields.get(f) == p_fields.get(f) for f in ('b', 'g')
                    )
                if not coherent:
                    old_rib = sec.rib
                    sec.rib = generate_rib_for_secondary(primary.rib, primary.country)
                    sec.save(update_fields=['rib', 'updated_at'])
                    self.stdout.write(
                        f"  {sec.account_id} ({sec.get_account_type_display()})\n"
                        f"    avant  : {old_rib}\n"
                        f"    après  : {sec.rib}"
                    )
                    fixed += 1

        if fixed:
            self.stdout.write(self.style.SUCCESS(f"\n{fixed} compte(s) corrigé(s)."))
        else:
            self.stdout.write(self.style.SUCCESS("Tous les RIBs sont déjà cohérents."))

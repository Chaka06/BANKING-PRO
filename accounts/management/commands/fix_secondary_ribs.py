"""
Corrige les comptes secondaires (épargne) dont le code guichet ou la clé RIB
diffèrent du compte primaire (courant) du même utilisateur.
Seul le numéro de compte (positions 14-25) est régénéré ; tous les autres
composants sont copiés depuis le compte primaire.
"""
from django.core.management.base import BaseCommand
from accounts.models import BankAccount
from accounts.services import generate_rib_for_secondary


class Command(BaseCommand):
    help = "Aligne les RIBs des comptes secondaires sur le compte primaire"

    def handle(self, *args, **options):
        fixed = 0
        for primary in BankAccount.objects.filter(is_primary=True).select_related('user', 'bank'):
            secondaries = BankAccount.objects.filter(
                user=primary.user, bank=primary.bank, is_primary=False
            )
            for sec in secondaries:
                same_guichet = sec.rib[9:14] == primary.rib[9:14]
                same_cle     = sec.rib[25:27] == primary.rib[25:27]
                same_check   = sec.rib[2:4]   == primary.rib[2:4]
                if not (same_guichet and same_cle and same_check):
                    old_rib = sec.rib
                    sec.rib = generate_rib_for_secondary(primary.rib)
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

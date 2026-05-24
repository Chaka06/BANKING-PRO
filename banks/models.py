from django.db import models


class Bank(models.Model):
    name = models.CharField(max_length=200, verbose_name="Nom de la banque")
    slug = models.SlugField(unique=True, verbose_name="Slug (URL de connexion)")
    logo = models.ImageField(upload_to='banks/logos/', verbose_name="Logo")
    tagline = models.CharField(max_length=300, blank=True, verbose_name="Slogan")

    address = models.TextField(verbose_name="Adresse du siège")
    phone = models.CharField(max_length=30, verbose_name="Téléphone")
    email = models.EmailField(verbose_name="Email officiel")
    website = models.URLField(blank=True, verbose_name="Site web")
    swift = models.CharField(max_length=11, verbose_name="Code SWIFT/BIC")
    bank_code = models.CharField(max_length=10, verbose_name="Code banque")
    country = models.CharField(max_length=100, default='France', verbose_name="Pays siège")

    # Charte graphique
    color_primary = models.CharField(max_length=7, default='#1a3a5c', verbose_name="Couleur primaire")
    color_secondary = models.CharField(max_length=7, default='#2ecc71', verbose_name="Couleur secondaire")
    color_accent = models.CharField(max_length=7, default='#f39c12', verbose_name="Couleur accent")
    color_text_on_primary = models.CharField(max_length=7, default='#ffffff', verbose_name="Texte sur couleur primaire")
    color_background = models.CharField(max_length=7, default='#f8f9fa', verbose_name="Couleur arrière-plan")
    color_card = models.CharField(max_length=7, default='#1a3a5c', verbose_name="Couleur carte bancaire")
    color_card_text = models.CharField(max_length=7, default='#ffffff', verbose_name="Texte sur carte bancaire")

    is_active = models.BooleanField(default=True, verbose_name="Banque active")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Banque"
        verbose_name_plural = "Banques"
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_login_url(self):
        return f"/{self.slug}/login/"

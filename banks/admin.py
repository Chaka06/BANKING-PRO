from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import Bank


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'country', 'swift', 'color_preview', 'is_active']
    list_filter = ['is_active', 'country']
    search_fields = ['name', 'slug', 'swift']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['color_preview_full', 'login_url_preview']

    fieldsets = (
        ('Identité', {
            'fields': ('name', 'slug', 'logo', 'tagline', 'is_active')
        }),
        ('Coordonnées', {
            'fields': ('address',)
        }),
        ('Informations bancaires', {
            'fields': ('swift', 'bank_code', 'country')
        }),
        ('Charte graphique', {
            'fields': (
                'color_primary', 'color_secondary', 'color_accent',
                'color_text_on_primary', 'color_background',
                'color_card', 'color_card_text',
                'color_preview_full',
            )
        }),
        ('SEO & Partage de lien', {
            'fields': ('favicon', 'meta_description', 'og_image'),
            'description': (
                'Favicon : icône affichée dans l\'onglet du navigateur (.ico, .png ou .svg).<br>'
                'Description SEO : texte affiché dans les résultats de recherche (160 car. max).<br>'
                'Image de partage : image affichée lors du partage du lien de connexion sur WhatsApp, '
                'iMessage, réseaux sociaux, etc. Format recommandé : 1200×630 px.'
            ),
        }),
        ('Documents officiels', {
            'fields': ('stamp',),
            'description': (
                'Cachet officiel apposé sur tous les PDFs (RIB, bordereaux, relevés). '
                'Format recommandé : PNG avec fond transparent, carré (ex: 400×400 px). '
                'Le cachet sera affiché incliné sur les documents, comme un vrai tampon.'
            ),
        }),
        ('URL de connexion', {
            'fields': ('login_url_preview',)
        }),
    )

    def color_preview(self, obj):
        return format_html(
            '<span style="display:inline-block;width:24px;height:24px;background:{};border-radius:4px;border:1px solid #ccc;vertical-align:middle;margin-right:4px;"></span>'
            '<span style="display:inline-block;width:24px;height:24px;background:{};border-radius:4px;border:1px solid #ccc;vertical-align:middle;"></span>',
            obj.color_primary, obj.color_secondary
        )
    color_preview.short_description = 'Couleurs'

    def color_preview_full(self, obj):
        swatches = [
            (obj.color_primary, 'Primaire'),
            (obj.color_secondary, 'Secondaire'),
            (obj.color_accent, 'Accent'),
            (obj.color_background, 'Arrière-plan'),
            (obj.color_card, 'Carte'),
        ]
        parts = [mark_safe('<div style="display:flex;gap:12px;flex-wrap:wrap;">')]
        for color, label in swatches:
            parts.append(format_html(
                '<div style="text-align:center;">'
                '<div style="width:60px;height:40px;background:{};border-radius:6px;border:1px solid #ccc;"></div>'
                '<small>{}<br>{}</small>'
                '</div>',
                color, label, color
            ))
        parts.append(mark_safe('</div>'))
        return mark_safe(''.join(str(p) for p in parts))
    color_preview_full.short_description = 'Aperçu des couleurs'

    def login_url_preview(self, obj):
        url = obj.get_login_url()
        return format_html('<a href="{}" target="_blank">{}</a>', url, url)
    login_url_preview.short_description = 'URL de connexion'

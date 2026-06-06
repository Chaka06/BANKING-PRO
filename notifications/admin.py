from django.contrib import admin
from django.utils.html import format_html
from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['title', 'account', 'type_badge', 'is_read', 'created_at']
    list_filter = ['notification_type', 'is_read', 'account__bank']
    list_select_related = ['account', 'account__bank']
    search_fields = ['title', 'message', 'account__first_name', 'account__last_name', 'account__account_id']
    ordering = ['-created_at']

    fieldsets = (
        (None, {
            'fields': ('account', 'title', 'message', 'notification_type', 'is_read')
        }),
    )

    def type_badge(self, obj):
        styles = {
            'info': ('#cce5ff', '#004085', 'ℹ️ Info'),
            'success': ('#d4edda', '#155724', '✅ Succès'),
            'warning': ('#fff3cd', '#856404', '⚠️ Avert.'),
            'danger': ('#f8d7da', '#721c24', '🚨 Alerte'),
        }
        bg, fg, label = styles.get(obj.notification_type, ('#e2e3e5', '#383d41', obj.notification_type))
        return format_html(
            '<span style="background:{};color:{};padding:2px 8px;border-radius:10px;font-size:11px;">{}</span>',
            bg, fg, label
        )
    type_badge.short_description = 'Type'

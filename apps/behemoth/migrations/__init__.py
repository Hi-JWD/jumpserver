# TODO 测试，最后删除

platform_data = {
    "category": "worker",
    "type": "worker",
    "internal": True,
    "charset": "utf-8",
    "domain_enabled": False,
    "su_enabled": False,
    "name": "Worker",
    "automation": {
        "ansible_enabled": False,
        "ansible_config": {
            "ansible_connection": "smart"
        },
        "ping_enabled": True,
        "ping_method": "ping_by_ssh",
        "gather_facts_enabled": False,
        "gather_accounts_enabled": False,
        "verify_account_enabled": False,
        "change_secret_enabled": False,
        "push_account_enabled": False,
    },
    "protocols": [
        {
            "name": "ssh",
            "port": 22,
            "setting": {
                "sftp_enabled": True,
                "sftp_home": "/tmp"
            },
            "primary": True,
            "required": False,
            "default": False
        }
    ]
}


def create_worker_platforms(apps, *args):
    platform_cls = apps.get_model('assets', 'Platform')
    automation_cls = apps.get_model('assets', 'PlatformAutomation')
    automation_data = platform_data.pop('automation', {})
    protocols_data = platform_data.pop('protocols', [])
    name = platform_data['name']
    platform, created = platform_cls.objects.update_or_create(
        defaults=platform_data, name=name
    )
    if created:
        automation = automation_cls.objects.create()
        platform.automation = automation
        platform.save()
    else:
        automation = platform.automation
    for k, v in automation_data.items():
        setattr(automation, k, v)
    automation.save()

    platform.protocols.all().delete()
    for p in protocols_data:
        platform.protocols.create(**p)


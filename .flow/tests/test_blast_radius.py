from flow.blast_radius import BlastRadiusInput, compute_blast_radius


def test_low_for_small_change():
    inp = BlastRadiusInput(files_changed=["src/foo.py"], lines_changed=20)
    assert compute_blast_radius(inp) == "low"


def test_high_for_migration():
    inp = BlastRadiusInput(files_changed=["migrations/0001.sql"], lines_changed=10)
    assert compute_blast_radius(inp) == "medium"  # 3 = medium


def test_high_for_migration_plus_size():
    inp = BlastRadiusInput(files_changed=["migrations/0001.sql"], lines_changed=600)
    assert compute_blast_radius(inp) == "high"  # 3 + 2 = 5


def test_core_module_bumps():
    inp = BlastRadiusInput(files_changed=["src/auth/jwt.py"], lines_changed=50)
    assert compute_blast_radius(inp, core_modules=["src/auth"]) == "medium"


def test_public_api_only():
    inp = BlastRadiusInput(files_changed=["src/api/v1/users.py"], lines_changed=10)
    assert compute_blast_radius(inp) == "medium"  # 2

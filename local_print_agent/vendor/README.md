# Print agent vendor runtime

Teller PCs should not need internet or a system-wide Python install.

## What goes here

| Path | Role |
|------|------|
| `../python/` | Embeddable CPython 3.12 + pywin32 (created by prepare; gitignored) |
| `_staging/` | Cached download zips/wheels (gitignored) |

## Build on a networked Windows machine

From `local_print_agent\`:

```bat
prepare_vendor.bat
```

Or:

```bat
python prepare_vendor.py
```

This downloads:

- Official Python 3.12 embeddable (amd64)
- Matching `pywin32` wheel (`cp312` / `win_amd64`)

Then installs pywin32 into `../python/` and writes `../python/VERSION.txt`.

After prepare succeeds, Admin → **Print Agent** → Download includes the bundled runtime so cashier PCs stay offline.

from folio.app import main

# Guarded: worker processes are spawned and re-import the main module.
if __name__ == "__main__":
    raise SystemExit(main())

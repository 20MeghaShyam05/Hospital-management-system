# Feature-Sliced Fractal Layout

This copy is the fractal version of DPAMS.

## Structure

- `app.py`
  - root ASGI entrypoint for `uvicorn app:app --reload`
- `features/core/`
  - bootstrap, dependency wiring, app container, and cross-cutting contracts
- `features/auth/`
  - login and password-change contracts, router, and module service
- `features/patients/`
  - patient-specific contracts, router, and feature service
- `features/doctors/`
  - doctor-specific contracts, router, and feature service
- `features/scheduling/`
  - availability and slot contracts, router, and feature service
- `features/appointments/`
  - booking, cancellation, and reschedule contracts, router, and feature service
- `features/queue/`
  - queue contracts, router, and feature service
- `features/reports/`
  - report contracts, router, and feature service
- `features/shared/`
  - shared infrastructure and domain code reused by the feature modules

## Architecture Intent

The runtime flow is centered on feature modules, not a top-level `api/`,
`services/`, `database/`, or `models/` layer split. Shared code now lives under
`features/shared/`, and the application boots directly from `app.py`.

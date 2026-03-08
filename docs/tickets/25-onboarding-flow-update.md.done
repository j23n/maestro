# Update onboarding flow for new auth

**Area:** `routes/lezione.py`, `templates/lezione-activity-onboarding.html`
**Roadmap:** [01-auth](../roadmap/01-auth.md)
**Depends on:** #22 (auth rewrite)

## Goal

Adapt the A0 onboarding flow to work with the new Account-based auth. Currently, onboarding captures the student's name in lesson 1. With auth, the student's email is known at signup, but we still need to capture name and persona.

## Work

### Review current onboarding

The A0 lesson 1 onboarding activity (`POST /lezione/{id}/activity/{idx}/onboarding-submit`) saves:
- `name` → `Student.name`
- `persona_tags` → `LearningProfile.persona.tags`

This still makes sense — signup collects email/password, onboarding collects name/learning preferences.

### Changes needed

- Verify the onboarding submit route works with the new auth dependency (it uses `get_current_student` which is being rewritten in #22)
- The `Student` is now created during signup (#21) with an empty name — onboarding fills it in, same as before
- No template changes expected, but verify the flow end-to-end

### Landing page update

- Update `templates/landing.html` CTA button: should link to `/auth/signup` instead of `/students/`
- Update any references to the students page

## Tests

- Integration: full flow — signup → first lesson → onboarding submit → name saved on Student
- Check that existing A0 onboarding tests pass with the new auth

## Notes

- This is mostly a verification/adaptation ticket, not new feature work. The risk is that the auth rewrite (#22) breaks the onboarding flow silently.

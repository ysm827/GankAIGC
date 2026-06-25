# Polish admin user management UI

## Goal

Fix the admin user management page visual issues reported from screenshots while preserving existing user-management behavior.

## Requirements

- User list table must use the available card width and avoid a large empty right gutter before the user-detail side panel.
- Remove the top-right quick filter group (`全部 / 近7天 / VIP / 异常`) because role/status filters below already cover the useful filtering paths.
- Remove the inert three-dot button from the user detail panel header.
- Normal-user and VIP badges in the user detail identity card must share the same horizontal badge placement/layout; the normal-user badge must not become vertical text.
- Replace the row action three-dot icon used for unlimited-credit toggle with a more explicit icon/label affordance; keep the existing unlimited toggle behavior.
- Keep existing user search, role/status filters, export, add-user, edit, beer adjustment, unlimited toggle, row selection, and user detail display working.
- Production frontend build must be synced into `package/static`.

## Acceptance Criteria

- [ ] Admin user-management source no longer renders the duplicate quick filter group labels `近7天`, `VIP`, and `异常` as the top-right segmented control.
- [ ] User detail header no longer renders an unused three-dot menu button.
- [ ] Detail identity role badge uses a shared horizontal badge class for normal and VIP users.
- [ ] The user list card/table can grow to full available width instead of fixed-width rows leaving large empty space.
- [ ] The unlimited-credit row action no longer uses a generic three-dot icon as the visible control.
- [ ] Static frontend tests cover these UI contracts.
- [ ] `npm run build` passes and `package/static` is synchronized.

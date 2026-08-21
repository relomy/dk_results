# NotificationStore separate from ContestDatabase

Announcement bookkeeping and VIP presence persist in a `NotificationStore`, keeping `ContestDatabase` contest-only, because contest rows and notification records have different lifecycles. The two stores share one sqlite file; the rejected alternative was folding both onto `ContestDatabase`.

# Artist deal guide

Every show carries one of three deal structures. The structure and its numbers
are copied onto the settlement when the packet is prepared, so a later edit to
the show cannot change a payout that was already reviewed.

## FLAT

The artist receives a fixed guarantee. The venue keeps the rest of the pool.

```text
guarantee = $1,200.00
pool      = $2,786.00
payout    = $1,200.00
```

A FLAT deal still needs a complete packet. A missing receipt can hold the
guarantee even though the arithmetic is simple.

## PERCENTAGE

The artist receives a share of the pool and no guarantee.

```text
pool       = $2,845.00
share      = 70.00% (7000 basis points)
payout     = round_half_up(284500 * 7000 / 10000)
           = $1,991.50
```

A pure percentage deal can pay zero when the pool is zero. That is rare, but it
is a legitimate result rather than a missing guarantee. The reviewer still
blocks a zero payout on a played show when the deal has a guarantee.

## VS

The artist receives the greater of the guarantee and the percentage share. This
is the most common deal for a touring act because it protects the artist on a
weak night and shares the upside on a strong one.

```text
pool       = $4,235.00
share      = 65.00% (6500 basis points)
share pay  = $2,752.75
guarantee  = $900.00
payout     = max(90000, 275275)
           = $2,752.75
```

The reviewer says which side won and by how much. If the guarantee wins, the
percentage share is still reported so the manager can see how close the show
came to the break point.

## Recoupment

Recoupable expenses come out of the pool before the artist share is calculated.
The deal cap limits how much the venue can recoup from a single show.

```text
recoupable_total = $5,750.00
expense_cap      = $5,500.00
recouped         = $5,500.00
over_cap         = $250.00
pool             = max(0, net_box_office - 550000)
```

The overage is house-absorbed. It never reduces the artist payout. A cap overage
is a watch item because it may point at a deal that no longer matches the room's
costs; it becomes a block only when the overage is more than 20 percent of the
cap.

## Comps and fees

Comps are free admissions. They are counted against the venue's allowance, not
subtracted from ticket revenue. Processor fees are subtracted from gross ticket
revenue before recoupment. A fee share above 5.00 percent is a watch item and
above 8.00 percent is a block, because either means the ticketing arrangement is
costing more than the deal assumed.

## What the manager sees

The settlement stores the inputs and the result side by side: ticket revenue,
fees, net box office, recoupable total, cap, recouped amount, overage, pool, deal
type, guarantee, share, and calculated payout. The approval form shows the
calculated amount and lets the manager change it with a written reason.

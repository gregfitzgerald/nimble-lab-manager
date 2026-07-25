-- Lab Operations Database -- sample data (synthetic; no real people or PII)
-- Dates are chosen relative to a "today" of 2026-07-01 so the operational
-- queries surface realistic overdue / low-stock / expiring cases.

INSERT INTO staff (staff_id, full_name, role, email, hire_date) VALUES
 (1, 'A. Rivera',   'PI',           'pi@example.edu',      '2015-01-05'),
 (2, 'J. Chen',     'Lab Manager',  'manager@example.edu', '2019-03-11'),
 (3, 'M. Okafor',   'Postdoc',      'postdoc@example.edu', '2023-09-01'),
 (4, 'S. Patel',    'Technician',   'tech@example.edu',    '2024-06-17'),
 (5, 'L. Nguyen',   'Undergraduate',NULL,                  '2025-09-02');

INSERT INTO protocols (protocol_id, title, pi_staff_id, approved_date, renewal_due, status) VALUES
 (101, 'Rodent models of cognitive decline',        1, '2025-06-10', '2026-06-15', 'active'),  -- OVERDUE
 (102, 'Environmental enrichment behavioral assays', 1, '2025-07-18', '2026-07-20', 'active'),  -- due soon
 (103, 'Whole-brain imaging pilot',                  1, '2025-12-01', '2026-12-01', 'active');   -- fine

INSERT INTO animals (animal_id, strain, sex, date_of_birth, protocol_id, cage, status) VALUES
 (1001, 'C57BL/6J',    'M', '2026-01-15', 101, 'A1', 'alive'),
 (1002, 'C57BL/6J',    'F', '2026-01-15', 101, 'A1', 'alive'),
 (1003, 'C57BL/6J',    'M', '2025-11-02', 101, 'A2', 'alive'),
 (1004, 'Sprague-Dawley','F','2025-10-20',102, 'B1', 'alive'),
 (1005, 'Sprague-Dawley','M','2025-10-20',102, 'B1', 'alive'),
 (1006, 'Sprague-Dawley','F','2026-03-05',102, 'B2', 'alive'),
 (1007, 'CNTNAP2-KO',  'M', '2026-02-11', 103, 'C1', 'alive'),
 (1008, 'CNTNAP2-KO',  'F', '2026-02-11', 103, 'C1', 'euthanized'),
 (1009, 'C57BL/6J',    'F', '2025-08-30', 101, 'A2', 'transferred');

INSERT INTO inventory (item_id, item_name, vendor, unit, quantity_on_hand, reorder_threshold, unit_cost, category, sds_url) VALUES
 (1, 'Isoflurane',            'VetOne',     'bottle', 2,  3,  95.00, 'chemical',  'https://example.com/sds/isoflurane.pdf'),   -- LOW
 (2, 'Ketamine',              'Covetrus',   'vial',   1,  2, 42.50,  'chemical',  'https://example.com/sds/ketamine.pdf'),    -- LOW
 (3, '4% Paraformaldehyde',   'Sigma',      'L',      6,  4, 78.00,  'chemical',  'https://example.com/sds/paraformaldehyde-4pct.pdf'),
 (4, 'Anti-GABA antibody',    'Abcam',      'vial',   0,  1, 320.00, 'antibody',  NULL),   -- OUT
 (5, 'Microscope slides',     'Fisher',     'box',    12, 5, 18.75,  'supply',    NULL),
 (6, 'Pipette tips 200uL',    'Rainin',     'box',    3,  6, 64.00,  'supply',    NULL);    -- LOW

INSERT INTO orders (order_id, item_id, quantity, order_date, unit_cost, ordered_by) VALUES
 (1, 1, 4, '2026-04-08', 92.00,  2),
 (2, 3, 2, '2026-04-22', 78.00,  2),
 (3, 4, 2, '2026-05-03', 315.00, 2),
 (4, 2, 3, '2026-05-19', 42.50,  4),
 (5, 5, 6, '2026-06-02', 18.75,  4),
 (6, 6, 4, '2026-06-25', 64.00,  2),
 (7, 1, 4, '2026-06-28', 95.00,  2);

INSERT INTO training (training_id, staff_id, course, completed_date, expires_date) VALUES
 (1, 2, 'IACUC Core',            '2024-05-01', '2026-05-01'),  -- EXPIRED
 (2, 3, 'Bloodborne Pathogens',  '2025-08-15', '2026-08-15'),  -- expiring soon
 (3, 4, 'Rodent Surgery',        '2025-10-01', '2027-10-01'),
 (4, 2, 'Rodent Surgery',        '2025-02-10', '2027-02-10'),
 (5, 5, 'IACUC Core',            '2025-09-10', '2026-09-10');   -- expiring soon

-- =====================================================================
-- NIMBLE LAB MANAGER extension seed data
-- 'today' for the demo is 2026-07-04. Spatial layout on floor_id=1.
-- =====================================================================

-- One floor so every location_node.floor_id below resolves. image_filename=NULL
-- means the map is drawn as an abstract schematic in 0..1000 canvas space
-- (no real floor-plan image ships with the seed).
INSERT INTO floor (id, name, image_filename, image_width, image_height) VALUES
 (1, 'Main Floor', NULL, NULL, NULL);

INSERT INTO location_node (id, parent_id, kind, name, capacity_rows, capacity_cols, floor_id, map_x, map_y, map_w, map_h) VALUES
 (1,NULL,'room','Room 201 - Wet Lab',NULL,NULL,1,40,40,560,560),
 (2,NULL,'room','Room 202 - Vivarium',NULL,NULL,1,640,40,320,560),
 (10,1,'freezer','-80C Freezer',NULL,NULL,1,80,100,150,150),
 (11,1,'fridge','4C Fridge',NULL,NULL,1,270,100,120,150),
 (12,1,'cabinet','Flammables Cabinet',NULL,NULL,1,430,100,130,130),
 (13,1,'bench','Bench 1',NULL,NULL,1,80,320,220,90),
 (14,1,'bench','Bench 2',NULL,NULL,1,80,450,220,90),
 (20,10,'shelf','Shelf 1',NULL,NULL,NULL,NULL,NULL,NULL,NULL),
 (21,10,'shelf','Shelf 2',NULL,NULL,NULL,NULL,NULL,NULL,NULL),
 (30,20,'box','Box A1 (RNA)',9,9,NULL,NULL,NULL,NULL,NULL),
 (31,20,'box','Box A2 (Abs)',9,9,NULL,NULL,NULL,NULL,NULL),
 (32,21,'box','Box B1 (Enz)',9,9,NULL,NULL,NULL,NULL,NULL),
 (40,2,'rack','Rack 1',NULL,NULL,1,680,100,110,200),
 (41,2,'rack','Rack 2',NULL,NULL,1,820,100,110,200),
 (50,40,'cage','A1',NULL,NULL,1,690,120,90,40),
 (51,40,'cage','A2',NULL,NULL,1,690,175,90,40),
 (52,40,'cage','B1',NULL,NULL,1,690,230,90,40),
 (53,41,'cage','B2',NULL,NULL,1,830,120,90,40),
 (54,41,'cage','C1',NULL,NULL,1,830,175,90,40);

INSERT INTO inventory (item_id, item_name, vendor, unit, quantity_on_hand, reorder_threshold, unit_cost, category, sds_url) VALUES
 (7,'DMEM High Glucose','Gibco','bottle',8,4,24.50,   'media',    NULL),
 (8,'Fetal Bovine Serum','Gibco','bottle',3,4,210.00, 'media',    NULL),
 (9,'Trypsin-EDTA 0.25%','Gibco','bottle',5,3,31.00,  'reagent',  'https://example.com/sds/trypsin-edta.pdf'),
 (10,'Penicillin-Streptomycin','Gibco','vial',6,4,28.00, 'media', NULL),
 (11,'Taq DNA Polymerase','NEB','vial',4,2,145.00,    'enzyme',   NULL),
 (12,'dNTP Mix 10mM','NEB','tube',9,4,58.00,          'reagent',  'https://example.com/sds/dntp-mix-10mm.pdf'),
 (13,'Anti-NeuN antibody','Millipore','vial',2,1,385.00, 'antibody', NULL),
 (14,'Anti-GFAP antibody','Dako','vial',1,2,298.00,   'antibody', NULL),
 (15,'PBS 10x','Fisher','L',10,5,22.00,               'reagent',  'https://example.com/sds/pbs-10x.pdf'),
 (16,'Tris-HCl 1M pH 8.0','Sigma','L',7,3,34.50,      'reagent',  'https://example.com/sds/tris-hcl-1m.pdf'),
 (17,'Agarose','Bio-Rad','box',2,3,156.00,            'reagent',  'https://example.com/sds/agarose.pdf'),
 (18,'Nitrile gloves M','Kimberly-Clark','box',20,8,12.50, 'supply', NULL);

INSERT INTO item_lot (id, item_id, lot_number, expiry_date, quantity, received_date) VALUES
 (1,1,'ISO-2411','2026-11-30',2,'2026-03-01'),
 (2,2,'KET-2508','2026-07-20',1,'2026-02-14'),
 (3,3,'PFA-2405','2026-06-15',2,'2026-01-20'),
 (4,3,'PFA-2509','2026-09-30',4,'2026-05-02'),
 (5,5,'SLD-2401',NULL,12,'2026-01-10'),
 (6,6,'TIP-2506',NULL,3,'2026-06-01'),
 (7,7,'DMEM-2606','2026-08-20',4,'2026-04-10'),
 (8,7,'DMEM-2612','2026-12-01',4,'2026-06-15'),
 (9,8,'FBS-2701','2027-01-15',3,'2026-05-22'),
 (10,9,'TRP-2507','2026-07-15',2,'2026-03-30'),
 (11,9,'TRP-2510','2026-10-10',3,'2026-06-05'),
 (12,10,'PS-2405','2026-05-20',2,'2026-01-15'),
 (13,10,'PS-2511','2026-11-05',4,'2026-05-18'),
 (14,11,'TAQ-2612','2026-12-31',4,'2026-04-01'),
 (15,12,'DNTP-2703','2027-03-01',9,'2026-05-10'),
 (16,13,'NEUN-2507','2026-07-25',2,'2026-03-12'),
 (17,14,'GFAP-2406','2026-06-01',1,'2026-01-08'),
 (18,15,'PBS-2706','2027-06-01',10,'2026-06-20'),
 (19,16,'TRIS-2702','2027-02-01',7,'2026-04-25'),
 (20,17,'AGR-2503',NULL,2,'2026-03-05'),
 (21,18,'GLV-2506',NULL,20,'2026-06-02'),
 (22,13,'NEUN-2601','2026-12-15',0,'2026-06-01'),
 (23,11,'TAQ-2606','2026-11-20',0,'2026-04-15');

-- Lot-specific Certificate of Analysis links on a few lots where a CoA applies
-- (serum, enzymes, antibodies). Illustrative placeholder URLs; remaining lots --
-- including plain supplies like slides and gloves -- keep coa_url NULL.
UPDATE item_lot SET coa_url = 'https://example.com/coa/FBS-2701.pdf'  WHERE lot_number = 'FBS-2701';
UPDATE item_lot SET coa_url = 'https://example.com/coa/TAQ-2612.pdf'  WHERE lot_number = 'TAQ-2612';
UPDATE item_lot SET coa_url = 'https://example.com/coa/NEUN-2507.pdf' WHERE lot_number = 'NEUN-2507';
UPDATE item_lot SET coa_url = 'https://example.com/coa/GFAP-2406.pdf' WHERE lot_number = 'GFAP-2406';

INSERT INTO container (id, item_lot_id, box_id, row, col, expected_box_id, expected_row, expected_col, status) VALUES
 (1,16,30,1,1,30,1,1,'in_use'),
 (2,16,30,1,2,30,1,2,'in_use'),
 (3,7,30,1,3,30,1,3,'in_use'),
 (4,22,30,1,4,30,1,4,'in_use'),
 (5,22,30,1,5,30,1,5,'in_use'),
 (6,22,30,1,6,30,1,6,'in_use'),
 (7,16,30,2,1,30,2,1,'in_use'),
 (8,16,30,2,2,30,2,2,'in_use'),
 (9,8,30,2,3,30,2,3,'in_use'),
 (10,16,30,2,4,30,2,4,'in_use'),
 (11,16,30,2,5,30,2,5,'in_use'),
 (12,16,30,2,6,30,2,6,'in_use'),
 (13,22,30,3,1,30,3,1,'in_use'),
 (14,22,30,3,2,30,3,2,'in_use'),
 (15,16,30,3,3,30,3,3,'in_use'),
 (16,22,30,3,4,30,3,4,'in_use'),
 (17,8,30,3,5,30,3,5,'in_use'),
 (18,22,30,3,6,30,3,6,'in_use'),
 (19,8,30,4,1,30,4,1,'in_use'),
 (20,7,30,4,2,30,4,2,'in_use'),
 (21,16,30,4,3,30,4,3,'in_use'),
 (22,22,30,4,4,30,4,4,'in_use'),
 (23,8,30,4,5,30,4,5,'in_use'),
 (24,7,30,4,6,30,4,6,'in_use'),
 (25,7,30,5,1,30,5,1,'in_use'),
 (26,22,30,5,2,30,5,2,'in_use'),
 (27,22,30,5,3,30,5,3,'in_use'),
 (28,7,30,5,4,30,5,4,'in_use'),
 (29,16,30,5,5,30,5,5,'in_use'),
 (30,16,30,5,6,30,5,6,'in_use'),
 (31,16,30,6,1,30,6,1,'empty'),
 (32,16,30,6,2,30,6,2,'empty'),
 (33,22,31,1,1,31,1,1,'in_use'),
 (34,16,31,1,2,31,1,2,'in_use'),
 (35,22,31,1,3,31,1,3,'in_use'),
 (36,22,31,1,4,31,1,4,'in_use'),
 (37,17,31,1,5,31,1,5,'in_use'),
 (38,22,31,2,1,31,2,1,'in_use'),
 (39,16,31,2,2,31,2,2,'in_use'),
 (40,17,31,2,3,31,2,3,'in_use'),
 (41,22,31,2,4,31,2,4,'in_use'),
 (42,17,31,2,5,31,2,5,'in_use'),
 (43,16,31,3,1,31,3,1,'in_use'),
 (44,22,31,3,2,31,3,2,'in_use'),
 (45,16,31,3,3,31,3,3,'in_use'),
 (46,17,31,3,4,31,3,4,'in_use'),
 (47,22,31,3,5,31,3,5,'in_use'),
 (48,23,32,1,1,32,1,1,'in_use'),
 (49,23,32,1,2,32,1,2,'in_use'),
 (50,23,32,1,3,32,1,3,'in_use'),
 (51,23,32,2,1,32,2,1,'in_use'),
 (52,23,32,2,2,32,2,2,'in_use'),
 (53,23,32,2,3,32,2,3,'in_use'),
 (54,22,30,7,8,31,1,1,'in_use'),
 (55,23,30,7,9,32,1,1,'in_use'),
 (56,16,31,5,9,30,1,1,'in_use'),
 (57,17,32,4,4,31,3,6,'in_use');

-- usage_event: 87 rows (78 consume) across last 90 days
INSERT INTO usage_event (id, item_id, container_id, staff_id, event_type, quantity, occurred_at, note) VALUES
 (1,7,NULL,2,'consume',2,'2026-04-05 11:55:00',NULL),
 (2,18,NULL,3,'consume',4,'2026-04-05 10:29:00',NULL),
 (3,10,NULL,3,'consume',1,'2026-04-06 17:56:00',NULL),
 (4,13,NULL,4,'consume',2,'2026-04-08 16:48:00',NULL),
 (5,8,NULL,4,'consume',1,'2026-04-09 12:15:00',NULL),
 (6,7,NULL,2,'consume',2,'2026-04-13 09:59:00',NULL),
 (7,15,NULL,5,'consume',1,'2026-04-13 12:27:00',NULL),
 (8,6,NULL,2,'consume',3,'2026-04-14 13:03:00',NULL),
 (9,7,NULL,3,'consume',1,'2026-04-14 08:32:00',NULL),
 (10,13,NULL,4,'consume',2,'2026-04-16 09:56:00',NULL),
 (11,13,NULL,4,'consume',2,'2026-04-17 10:47:00',NULL),
 (12,3,NULL,4,'consume',1,'2026-04-18 17:35:00',NULL),
 (13,8,NULL,5,'consume',1,'2026-04-19 11:17:00',NULL),
 (14,12,NULL,5,'consume',1,'2026-04-19 11:12:00',NULL),
 (15,18,NULL,2,'consume',3,'2026-04-19 12:22:00',NULL),
 (16,5,NULL,3,'consume',3,'2026-04-21 13:27:00',NULL),
 (17,8,NULL,4,'consume',1,'2026-04-22 15:28:00',NULL),
 (18,15,NULL,4,'consume',3,'2026-04-22 09:52:00',NULL),
 (19,3,NULL,2,'consume',3,'2026-04-23 15:26:00',NULL),
 (20,18,NULL,5,'consume',1,'2026-04-24 15:16:00',NULL),
 (21,9,NULL,5,'consume',2,'2026-04-26 08:22:00',NULL),
 (22,15,NULL,5,'consume',1,'2026-04-27 10:55:00',NULL),
 (23,10,NULL,4,'consume',1,'2026-04-28 11:41:00',NULL),
 (24,18,NULL,5,'consume',1,'2026-04-30 15:06:00',NULL),
 (25,18,NULL,3,'consume',2,'2026-05-02 15:41:00',NULL),
 (26,3,NULL,4,'consume',3,'2026-05-03 11:25:00',NULL),
 (27,18,NULL,3,'consume',1,'2026-05-03 11:13:00',NULL),
 (28,15,NULL,4,'consume',1,'2026-05-04 10:40:00',NULL),
 (29,6,NULL,2,'consume',3,'2026-05-05 14:31:00',NULL),
 (30,7,NULL,2,'consume',1,'2026-05-05 10:09:00',NULL),
 (31,6,NULL,3,'consume',2,'2026-05-06 11:16:00',NULL),
 (32,11,NULL,5,'consume',1,'2026-05-06 17:30:00',NULL),
 (33,7,NULL,4,'consume',1,'2026-05-08 08:05:00',NULL),
 (34,12,NULL,4,'consume',2,'2026-05-08 17:02:00',NULL),
 (35,15,NULL,2,'consume',3,'2026-05-09 14:55:00',NULL),
 (36,18,NULL,2,'consume',3,'2026-05-10 16:26:00',NULL),
 (37,10,NULL,4,'consume',2,'2026-05-15 11:47:00',NULL),
 (38,18,NULL,4,'consume',4,'2026-05-15 08:18:00',NULL),
 (39,5,NULL,4,'consume',6,'2026-05-17 14:44:00',NULL),
 (40,5,NULL,5,'consume',1,'2026-05-18 12:49:00',NULL),
 (41,15,NULL,4,'consume',1,'2026-05-20 17:24:00',NULL),
 (42,18,NULL,3,'consume',1,'2026-05-20 15:01:00',NULL),
 (43,12,NULL,2,'consume',5,'2026-05-21 09:15:00',NULL),
 (44,10,NULL,4,'consume',2,'2026-05-22 11:28:00',NULL),
 (45,18,NULL,5,'consume',1,'2026-05-22 09:42:00',NULL),
 (46,5,NULL,4,'consume',5,'2026-05-23 11:08:00',NULL),
 (47,10,NULL,5,'consume',1,'2026-05-24 16:07:00',NULL),
 (48,18,NULL,4,'consume',3,'2026-05-24 15:41:00',NULL),
 (49,5,NULL,2,'consume',2,'2026-05-27 13:51:00',NULL),
 (50,7,NULL,4,'consume',1,'2026-05-27 09:26:00',NULL),
 (51,18,NULL,4,'consume',1,'2026-05-28 13:00:00',NULL),
 (52,5,NULL,2,'consume',1,'2026-05-29 09:47:00',NULL),
 (53,18,NULL,5,'consume',1,'2026-05-29 14:17:00',NULL),
 (54,12,NULL,3,'consume',2,'2026-05-30 12:13:00',NULL),
 (55,18,NULL,2,'consume',1,'2026-06-03 17:38:00',NULL),
 (56,15,NULL,2,'consume',2,'2026-06-05 16:43:00',NULL),
 (57,8,NULL,4,'consume',1,'2026-06-07 15:12:00',NULL),
 (58,18,NULL,4,'consume',10,'2026-06-10 11:24:00',NULL),
 (59,3,NULL,4,'consume',3,'2026-06-11 10:08:00',NULL),
 (60,5,NULL,5,'consume',1,'2026-06-11 10:48:00',NULL),
 (61,8,NULL,3,'consume',2,'2026-06-11 16:46:00',NULL),
 (62,8,NULL,4,'consume',2,'2026-06-12 11:36:00',NULL),
 (63,6,NULL,2,'consume',2,'2026-06-13 17:47:00',NULL),
 (64,12,NULL,3,'consume',1,'2026-06-14 12:22:00',NULL),
 (65,12,NULL,4,'consume',2,'2026-06-17 13:28:00',NULL),
 (66,7,NULL,4,'consume',3,'2026-06-19 12:54:00',NULL),
 (67,7,NULL,5,'consume',1,'2026-06-20 16:26:00',NULL),
 (68,6,NULL,2,'consume',3,'2026-06-21 16:09:00',NULL),
 (69,12,NULL,4,'consume',2,'2026-06-22 11:49:00',NULL),
 (70,15,NULL,4,'consume',1,'2026-06-22 12:30:00',NULL),
 (71,18,NULL,2,'consume',1,'2026-06-23 12:24:00',NULL),
 (72,9,NULL,2,'consume',2,'2026-06-25 14:08:00',NULL),
 (73,18,NULL,4,'consume',1,'2026-06-25 17:43:00',NULL),
 (74,12,NULL,2,'consume',1,'2026-06-26 10:45:00',NULL),
 (75,12,NULL,4,'consume',2,'2026-06-29 15:33:00',NULL),
 (76,16,NULL,3,'consume',2,'2026-07-03 14:56:00',NULL),
 (77,9,NULL,4,'consume',1,'2026-07-04 12:29:00',NULL),
 (78,18,NULL,5,'consume',6,'2026-07-04 12:45:00',NULL),
 (79,3,NULL,2,'restock',2,'2026-04-22 10:00:00','PO received: PFA'),
 (80,5,NULL,4,'restock',6,'2026-06-02 13:50:00','PO received: slides'),
 (81,6,NULL,2,'restock',4,'2026-06-25 12:36:00','PO received: tips'),
 (82,7,NULL,2,'restock',4,'2026-06-15 11:11:00','PO received: DMEM'),
 (83,1,NULL,2,'restock',4,'2026-06-28 17:54:00','PO received: Isoflurane'),
 (84,13,NULL,3,'move',NULL,'2026-06-22 14:52:00','Reorg: A2 -> A1'),
 (85,11,NULL,4,'move',NULL,'2026-06-29 14:32:00','Reorg: B1 shelf 2'),
 (86,3,NULL,4,'discard',1,'2026-06-14 13:05:00','Expired PFA lot PFA-2405'),
 (87,10,NULL,2,'expire',2,'2026-05-20 14:42:00','Pen-Strep lot expired');

-- =====================================================================
-- NIMBLE LAB MANAGER v2 seed: disposal, soft-delete, tickets, templates,
-- audit trail, and settings. Appended so existing ids above stay stable.
-- =====================================================================

-- Runtime config. usage_visibility gates who can see per-person usage;
-- po_approval_threshold is the dollar ceiling under which a requisition
-- auto-approves (stored as text, parsed as a number by the app).
INSERT INTO app_setting (key, value) VALUES
 ('usage_visibility', 'admin_only'),
 ('po_approval_threshold', '500');

-- Disposal guidance (from each product's SDS section 13) on chemical/reagent
-- and antibody items; plain supplies (slides, tips, gloves) and benign media
-- keep disposal_instructions NULL.
UPDATE inventory SET disposal_instructions =
  'See SDS section 13. Halogenated anesthetic waste -- do not pour down drain; collect in a sealed waste-anesthetic container.'
  WHERE item_id = 1;   -- Isoflurane
UPDATE inventory SET disposal_instructions =
  'Controlled substance. Dispose via a DEA-compliant reverse distributor; never pour down the drain (SDS section 13).'
  WHERE item_id = 2;   -- Ketamine
UPDATE inventory SET disposal_instructions =
  'See SDS section 13. Formaldehyde fixative -- collect as hazardous chemical waste; do not pour down drain.'
  WHERE item_id = 3;   -- 4% Paraformaldehyde
UPDATE inventory SET disposal_instructions =
  'Antibody in sodium-azide preservative -- dispose as hazardous waste per SDS section 13; azide reacts with plumbing metals.'
  WHERE item_id IN (4, 13, 14);  -- antibodies
UPDATE inventory SET disposal_instructions =
  'Biological reagent -- inactivate and dispose as biohazard waste per SDS section 13.'
  WHERE item_id = 9;   -- Trypsin-EDTA
UPDATE inventory SET disposal_instructions =
  'Aqueous nucleotide reagent -- dilute and dispose per SDS section 13; no special hazard.'
  WHERE item_id = 12;  -- dNTP Mix
UPDATE inventory SET disposal_instructions =
  'Non-hazardous buffer -- may be drain-disposed per SDS section 13 and local rules.'
  WHERE item_id = 15;  -- PBS 10x
UPDATE inventory SET disposal_instructions =
  'Buffer -- neutralize to pH 6-9 and dispose per SDS section 13.'
  WHERE item_id = 16;  -- Tris-HCl
UPDATE inventory SET disposal_instructions =
  'Solid reagent -- dispose as general lab solid waste per SDS section 13.'
  WHERE item_id = 17;  -- Agarose

-- Soft-delete one clearly-outdated item (a long-out-of-stock antibody) so the
-- deprecate flow has a demo case. All history (lots, orders) is preserved.
UPDATE inventory SET status = 'deprecated' WHERE item_id = 4;  -- Anti-GABA antibody (OUT since seed)

-- Task templates: recurring bench procedures pre-filling a ticket. item_ids map
-- to existing seed inventory rows.
INSERT INTO task_template (id, name, description) VALUES
 (1, 'Perfusion',      'Transcardial perfusion + fixation of rodents.'),
 (2, 'Western Blot',   'SDS-PAGE immunoblot for target protein.'),
 (3, 'Immunostaining', 'Fluorescent immunohistochemistry on fixed sections.'),
 (4, 'Genotyping PCR', 'Endpoint PCR genotyping of tail/ear samples.');

INSERT INTO task_template_line (id, template_id, item_id, default_quantity) VALUES
 (1, 1, 1,  1),   -- Perfusion: Isoflurane
 (2, 1, 2,  1),   -- Perfusion: Ketamine
 (3, 1, 3,  2),   -- Perfusion: 4% Paraformaldehyde
 (4, 1, 15, 1),   -- Perfusion: PBS 10x
 (5, 2, 13, 1),   -- Western Blot: Anti-NeuN antibody
 (6, 2, 16, 1),   -- Western Blot: Tris-HCl
 (7, 2, 15, 2),   -- Western Blot: PBS 10x
 (8, 3, 14, 1),   -- Immunostaining: Anti-GFAP antibody
 (9, 3, 15, 1),   -- Immunostaining: PBS 10x
 (10,3, 3,  1),   -- Immunostaining: 4% Paraformaldehyde
 (11,4, 11, 1),   -- Genotyping PCR: Taq DNA Polymerase
 (12,4, 12, 2),   -- Genotyping PCR: dNTP Mix
 (13,4, 15, 1);   -- Genotyping PCR: PBS 10x (as water/diluent)

-- Tickets over the last ~2 weeks. user_id is a soft ref to app_user(id):
-- manager=2, member=3 (created by ensure_demo_users after this seed loads).
INSERT INTO ticket (id, user_id, ticket_date, task, purpose, note, created_at) VALUES
 (1, 2, '2026-06-22', 'Perfusion',      'Perfusion',      'Cohort A perfusions',      '2026-06-22 09:40:00'),
 (2, 3, '2026-06-24', 'Western Blot',   'Western Blot',   'NeuN blot, gel 1',         '2026-06-24 13:20:00'),
 (3, 3, '2026-06-26', 'Genotyping PCR', 'Genotyping PCR', 'Litter 24 genotyping',     '2026-06-26 10:05:00'),
 (4, 2, '2026-06-29', 'Immunostaining', 'Immunostaining', 'GFAP IHC, slides 1-12',    '2026-06-29 14:15:00'),
 (5, 2, '2026-07-01', 'Genotyping PCR', 'Genotyping PCR', 'Re-run failed wells',      '2026-07-01 11:30:00'),
 (6, 3, '2026-07-02', 'Western Blot',   'Western Blot',   'NeuN blot, replicate',     '2026-07-02 15:10:00'),
 (7, 3, '2026-07-03', 'Perfusion',      'Perfusion',      'Cohort B perfusions',      '2026-07-03 09:55:00'),
 (8, 2, '2026-07-04', 'Immunostaining', 'Immunostaining', 'GFAP IHC, slides 13-20',   '2026-07-04 10:20:00');

INSERT INTO ticket_line (id, ticket_id, item_id, quantity) VALUES
 (1, 1, 1,  1), (2, 1, 3,  2), (3, 1, 15, 1),
 (4, 2, 13, 1), (5, 2, 16, 1),
 (6, 3, 11, 1), (7, 3, 12, 2), (8, 3, 15, 1),
 (9, 4, 14, 1), (10, 4, 15, 1), (11, 4, 3, 1),
 (12, 5, 11, 1), (13, 5, 12, 1),
 (14, 6, 13, 1), (15, 6, 16, 1), (16, 6, 15, 1),
 (17, 7, 1,  1), (18, 7, 15, 2),
 (19, 8, 14, 1), (20, 8, 3,  1);

-- Matching consume events carrying ticket_id + purpose (staff_id follows the
-- ticket owner: manager user2->staff2, member user3->staff4). Illustrative,
-- like the 78 consume rows above -- they do not change quantity_on_hand.
INSERT INTO usage_event (id, item_id, container_id, staff_id, event_type, quantity, occurred_at, note, ticket_id, purpose) VALUES
 (88, 1,  NULL, 2, 'consume', 1, '2026-06-22 09:45:00', NULL, 1, 'Perfusion'),
 (89, 3,  NULL, 2, 'consume', 2, '2026-06-22 09:47:00', NULL, 1, 'Perfusion'),
 (90, 15, NULL, 2, 'consume', 1, '2026-06-22 09:50:00', NULL, 1, 'Perfusion'),
 (91, 13, NULL, 4, 'consume', 1, '2026-06-24 13:25:00', NULL, 2, 'Western Blot'),
 (92, 16, NULL, 4, 'consume', 1, '2026-06-24 13:28:00', NULL, 2, 'Western Blot'),
 (93, 11, NULL, 4, 'consume', 1, '2026-06-26 10:10:00', NULL, 3, 'Genotyping PCR'),
 (94, 12, NULL, 4, 'consume', 2, '2026-06-26 10:12:00', NULL, 3, 'Genotyping PCR'),
 (95, 15, NULL, 4, 'consume', 1, '2026-06-26 10:15:00', NULL, 3, 'Genotyping PCR'),
 (96, 14, NULL, 2, 'consume', 1, '2026-06-29 14:20:00', NULL, 4, 'Immunostaining'),
 (97, 15, NULL, 2, 'consume', 1, '2026-06-29 14:22:00', NULL, 4, 'Immunostaining'),
 (98, 3,  NULL, 2, 'consume', 1, '2026-06-29 14:25:00', NULL, 4, 'Immunostaining'),
 (99, 11, NULL, 2, 'consume', 1, '2026-07-01 11:35:00', NULL, 5, 'Genotyping PCR'),
 (100,12, NULL, 2, 'consume', 1, '2026-07-01 11:37:00', NULL, 5, 'Genotyping PCR'),
 (101,13, NULL, 4, 'consume', 1, '2026-07-02 15:15:00', NULL, 6, 'Western Blot'),
 (102,16, NULL, 4, 'consume', 1, '2026-07-02 15:18:00', NULL, 6, 'Western Blot'),
 (103,15, NULL, 4, 'consume', 1, '2026-07-02 15:20:00', NULL, 6, 'Western Blot'),
 (104,1,  NULL, 4, 'consume', 1, '2026-07-03 10:00:00', NULL, 7, 'Perfusion'),
 (105,15, NULL, 4, 'consume', 2, '2026-07-03 10:03:00', NULL, 7, 'Perfusion'),
 (106,14, NULL, 2, 'consume', 1, '2026-07-04 10:25:00', NULL, 8, 'Immunostaining'),
 (107,3,  NULL, 2, 'consume', 1, '2026-07-04 10:28:00', NULL, 8, 'Immunostaining');

-- Audit trail seed so the History view has signal from first boot. username is
-- copied at write time; user_id is a soft ref to app_user(id).
INSERT INTO audit_log (id, occurred_at, user_id, username, action, entity_type, entity_id, detail) VALUES
 (1,  '2026-06-22 09:38:00', 2, 'manager', 'login',         NULL,         NULL, 'session start'),
 (2,  '2026-06-22 09:41:00', 2, 'manager', 'ticket.create', 'ticket',     1,    'Perfusion (3 lines)'),
 (3,  '2026-06-22 09:45:00', 2, 'manager', 'consume',       'inventory',  1,    'Isoflurane x1 (Perfusion)'),
 (4,  '2026-06-23 16:02:00', 1, 'admin',   'settings.update','app_setting',NULL,'usage_visibility -> admin_only'),
 (5,  '2026-06-24 13:18:00', 3, 'member',  'login',         NULL,         NULL, 'session start'),
 (6,  '2026-06-24 13:21:00', 3, 'member',  'ticket.create', 'ticket',     2,    'Western Blot (2 lines)'),
 (7,  '2026-06-24 13:25:00', 3, 'member',  'consume',       'inventory',  13,   'Anti-NeuN antibody x1 (Western Blot)'),
 (8,  '2026-06-25 12:36:00', 2, 'manager', 'restock',       'inventory',  6,    'Pipette tips 200uL +4 (PO received)'),
 (9,  '2026-06-26 10:06:00', 3, 'member',  'ticket.create', 'ticket',     3,    'Genotyping PCR (3 lines)'),
 (10, '2026-06-26 10:10:00', 3, 'member',  'consume',       'inventory',  11,   'Taq DNA Polymerase x1 (Genotyping PCR)'),
 (11, '2026-06-27 11:14:00', 2, 'manager', 'item.update',   'inventory',  3,    'reorder_threshold 4 -> 4; disposal note added'),
 (12, '2026-06-28 17:54:00', 2, 'manager', 'restock',       'inventory',  1,    'Isoflurane +4 (PO received)'),
 (13, '2026-06-29 14:16:00', 2, 'manager', 'ticket.create', 'ticket',     4,    'Immunostaining (3 lines)'),
 (14, '2026-06-29 14:20:00', 2, 'manager', 'consume',       'inventory',  14,   'Anti-GFAP antibody x1 (Immunostaining)'),
 (15, '2026-06-30 09:12:00', 1, 'admin',   'item.deprecate','inventory',  4,    'Anti-GABA antibody marked deprecated'),
 (16, '2026-06-30 14:52:00', 3, 'member',  'container.move','container',   33,   'Reorg: A2 -> A1'),
 (17, '2026-07-01 11:31:00', 2, 'manager', 'ticket.create', 'ticket',     5,    'Genotyping PCR (2 lines)'),
 (18, '2026-07-01 11:35:00', 2, 'manager', 'consume',       'inventory',  11,   'Taq DNA Polymerase x1 (Genotyping PCR)'),
 (19, '2026-07-02 15:11:00', 3, 'member',  'ticket.create', 'ticket',     6,    'Western Blot (3 lines)'),
 (20, '2026-07-02 15:15:00', 3, 'member',  'consume',       'inventory',  13,   'Anti-NeuN antibody x1 (Western Blot)'),
 (21, '2026-07-03 09:56:00', 3, 'member',  'ticket.create', 'ticket',     7,    'Perfusion (2 lines)'),
 (22, '2026-07-03 09:58:00', 4, 'viewer',  'login',         NULL,         NULL, 'session start'),
 (23, '2026-07-04 10:21:00', 2, 'manager', 'ticket.create', 'ticket',     8,    'Immunostaining (2 lines)'),
 (24, '2026-07-04 10:25:00', 2, 'manager', 'consume',       'inventory',  14,   'Anti-GFAP antibody x1 (Immunostaining)'),
 (25, '2026-07-04 12:30:00', 1, 'admin',   'login',         NULL,         NULL, 'session start');

-- =====================================================================
-- PURCHASING + CONTROLLED-SUBSTANCE REGISTER seed. Appended so existing
-- ids above stay stable. 'today' for the demo is 2026-07-04.
-- =====================================================================

-- Controlled substances. Ketamine (item 2) is DEA Schedule III; it goes on the
-- controlled register (running-balance log with witness). Isoflurane is an
-- anesthetic but is NOT DEA-scheduled, so it stays off the register. No other
-- seeded item is a controlled drug, so only Ketamine is flagged here.
UPDATE inventory SET is_controlled = 1, controlled_schedule = 'III' WHERE item_id = 2;  -- Ketamine

-- Controlled-substance register for Ketamine (item 2). Append-only, signed
-- changes with a running balance_after and a witness signature (regulatory
-- requirement). Opens with a received shipment (+5), then survival-surgery and
-- terminal-perfusion dispenses draw it down to the seeded quantity_on_hand (1).
-- user_id is a soft ref to app_user(id): manager=2, member=3.
INSERT INTO controlled_log (id, item_id, occurred_at, user_id, username, change, balance_after, reason, witness) VALUES
 (1, 2, '2026-06-14 10:05:00', 2, 'manager', 5,  5, 'Received shipment (KET-2508)', 'S. Patel'),
 (2, 2, '2026-06-22 09:44:00', 2, 'manager', -1, 4, 'Rodent survival surgery',      'A. Rivera'),
 (3, 2, '2026-06-26 10:52:00', 3, 'member',  -1, 3, 'Rodent survival surgery',      'J. Chen'),
 (4, 2, '2026-07-01 13:18:00', 2, 'manager', -1, 2, 'Terminal perfusion',           'M. Okafor'),
 (5, 2, '2026-07-03 09:58:00', 3, 'member',  -1, 1, 'Terminal perfusion',           'S. Patel');

-- Purchase orders across three lifecycle states. created_by is a soft ref to
-- app_user(id) = manager (2), matching the manager-owned tickets above. Receiving
-- a line would normally restock inventory; these demo rows only record the PO
-- (they intentionally do not mutate quantity_on_hand / item_lot).
INSERT INTO purchase_order (id, vendor, status, created_by, created_at, ordered_at, received_at, note) VALUES
 (1, 'Gibco', 'received', 2, '2026-06-10 09:15:00', '2026-06-11 10:00:00', '2026-06-15 11:11:00', 'Cell-culture media restock'),
 (2, 'NEB',   'ordered',  2, '2026-06-28 14:20:00', '2026-06-29 09:30:00', NULL,                  'PCR enzymes for genotyping'),
 (3, 'Fisher','draft',    2, '2026-07-03 16:05:00', NULL,                  NULL,                  'Bench consumables -- pending approval');

-- PO lines. The 'received' PO (1) has received_qty = quantity (fully received);
-- the 'ordered' (2) and 'draft' (3) POs have received_qty 0. item_ids and
-- unit_costs map to existing seed inventory rows.
INSERT INTO po_line (id, po_id, item_id, quantity, unit_cost, received_qty) VALUES
 (1, 1, 7,  4, 24.50,  4),    -- DMEM High Glucose
 (2, 1, 8,  3, 210.00, 3),    -- Fetal Bovine Serum
 (3, 2, 11, 2, 145.00, 0),    -- Taq DNA Polymerase
 (4, 2, 12, 4, 58.00,  0),    -- dNTP Mix 10mM
 (5, 3, 5,  6, 18.75,  0),    -- Microscope slides
 (6, 3, 18, 4, 12.50,  0);    -- Nitrile gloves M

-- =====================================================================
-- NIMBLE LAB MANAGER Wave 2 seed: bundled vendor catalog, substitute
-- groups, chemical-safety metadata, attached documents (SDS / CoA /
-- invoice), and the purchase-order approval workflow. Appended so every
-- id assigned above stays stable. 'today' for the demo is 2026-07-04.
--
-- Catalog products are REAL: real vendors, real catalog numbers, realistic
-- pack sizes and list prices, and manufacturer SDS / product URL patterns.
-- Certificate-of-Analysis documents are lot-specific and are NOT published
-- publicly, so the CoA links point at representative sample files shipped in
-- the repo under examples/coa/ (see examples/README.md).
-- =====================================================================

-- Substitute groups: sets of interchangeable products across vendors. The app
-- prices these against each other and falls through to the next-preferred
-- in-stock member when the preferred one is on backorder.
INSERT INTO substitute_group (id, name, category, description) VALUES
 (1, 'Paraformaldehyde, powder', 'chemical', 'Reagent-grade paraformaldehyde powder for making fresh fixative; interchangeable across suppliers.'),
 (2, 'DMEM, high glucose',       'media',    'High-glucose Dulbecco''s Modified Eagle Medium, 500 mL bottles.'),
 (3, 'Taq DNA polymerase',       'enzyme',   'Standard thermostable Taq polymerase for endpoint genotyping PCR.'),
 (4, 'Trypsin-EDTA 0.25%',       'reagent',  '0.25% trypsin-EDTA with phenol red for adherent-cell passaging.');

-- Vendor catalog. availability is the current supply state (in_stock, backorder,
-- discontinued). Within a substitute_group, preference_rank 1 = preferred; note
-- groups 1 and 3 have their rank-1 member on BACKORDER, so the "preferred in
-- stock" fall-through resolves to the rank-2 member.
INSERT INTO vendor_catalog
 (id, vendor, catalog_number, product_name, category, pack_size, unit, list_price,
  sds_url, product_url, cas_number, hazard_class, substitute_group_id, preference_rank, availability) VALUES
 -- group 1: Paraformaldehyde, powder (rank-1 Sigma is on backorder)
 (1,  'Sigma-Aldrich', 'P6148',      'Paraformaldehyde, reagent grade, powder',  'chemical', '500 g',  'g',      138.00, 'https://www.sigmaaldrich.com/US/en/sds/sigma/p6148', 'https://www.sigmaaldrich.com/US/en/product/sigma/p6148', '30525-89-4', 'toxic,irritant', 1, 1, 'backorder'),
 (2,  'Electron Microscopy Sciences', '19200', 'Paraformaldehyde, granular, EM grade', 'chemical', '500 g', 'g', 96.50, 'https://www.emsdiasum.com/sds/19200', 'https://www.emsdiasum.com/paraformaldehyde-granular', '30525-89-4', 'toxic,irritant', 1, 2, 'in_stock'),
 (3,  'Thermo Scientific', 'A11313', 'Paraformaldehyde, 96%',                     'chemical', '500 g',  'g',      84.00,  'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2FA11313_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/A11313', '30525-89-4', 'toxic,irritant', 1, 3, 'in_stock'),
 -- group 2: DMEM, high glucose (rank-3 Sigma on backorder)
 (4,  'Gibco',  '11965092',   'DMEM, high glucose, pyruvate',                     'media',    '500 mL', 'bottle', 24.30,  'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F11965092_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/11965092', NULL, NULL, 2, 1, 'in_stock'),
 (5,  'Corning', '10-013-CV', 'DMEM, high glucose with L-glutamine',              'media',    '500 mL', 'bottle', 21.75,  'https://ecatalog.corning.com/life-sciences/b2b/US/en/sds/10-013-CV', 'https://ecatalog.corning.com/life-sciences/b2b/US/en/Cell-Culture/Media/10-013-CV', NULL, NULL, 2, 2, 'in_stock'),
 (6,  'Sigma-Aldrich', 'D5796',     'DMEM, high glucose',                         'media',    '500 mL', 'bottle', 28.40,  'https://www.sigmaaldrich.com/US/en/sds/sigma/d5796', 'https://www.sigmaaldrich.com/US/en/product/sigma/d5796', NULL, NULL, 2, 3, 'backorder'),
 -- group 3: Taq DNA polymerase (rank-1 NEB is on backorder)
 (7,  'NEB',        'M0273',    'Taq DNA Polymerase with Standard Taq Buffer',    'enzyme',   '2000 units', 'vial', 145.00, 'https://www.neb.com/-/media/nebus/files/sds/m0273_sds.pdf', 'https://www.neb.com/en-us/products/m0273-taq-dna-polymerase-with-standard-taq-buffer', NULL, NULL, 3, 1, 'backorder'),
 (8,  'Invitrogen', '10342020', 'Platinum Taq DNA Polymerase',                    'enzyme',   '500 units',  'vial', 168.00, 'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F10342020_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/10342020', NULL, NULL, 3, 2, 'in_stock'),
 (9,  'Promega',    'M3001',    'GoTaq DNA Polymerase',                           'enzyme',   '500 units',  'vial', 132.00, 'https://www.promega.com/-/media/files/resources/sds/m300/m3001.pdf', 'https://www.promega.com/products/pcr/taq-polymerase/gotaq-dna-polymerase/', NULL, NULL, 3, 3, 'in_stock'),
 -- group 4: Trypsin-EDTA 0.25%
 (10, 'Gibco',   '25200056',  'Trypsin-EDTA (0.25%), phenol red',                 'reagent',  '100 mL', 'bottle', 31.20,  'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F25200056_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/25200056', NULL, 'irritant', 4, 1, 'in_stock'),
 (11, 'Corning', '25-053-CI', 'Trypsin-EDTA 0.25%',                               'reagent',  '100 mL', 'bottle', 27.80,  'https://ecatalog.corning.com/life-sciences/b2b/US/en/sds/25-053-CI', 'https://ecatalog.corning.com/life-sciences/b2b/US/en/Cell-Culture/25-053-CI', NULL, 'irritant', 4, 2, 'in_stock'),
 -- ungrouped catalog entries
 (12, 'Gibco',   '16000044',  'Fetal Bovine Serum, qualified, US origin',         'media',    '500 mL', 'bottle', 685.00, 'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F16000044_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/16000044', NULL, NULL, NULL, NULL, 'in_stock'),
 (13, 'Sigma-Aldrich', 'F2442', 'Fetal Bovine Serum',                             'media',    '500 mL', 'bottle', 549.00, 'https://www.sigmaaldrich.com/US/en/sds/sigma/f2442', 'https://www.sigmaaldrich.com/US/en/product/sigma/f2442', NULL, NULL, NULL, NULL, 'in_stock'),
 (14, 'Gibco',   '15140122',  'Penicillin-Streptomycin (10,000 U/mL)',            'media',    '100 mL', 'bottle', 28.60,  'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F15140122_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/15140122', NULL, NULL, NULL, NULL, 'in_stock'),
 (15, 'NEB',     'N0447',     'Deoxynucleotide (dNTP) Solution Mix, 10 mM',       'reagent',  '8 umol', 'tube',   62.00,  'https://www.neb.com/-/media/nebus/files/sds/n0447_sds.pdf', 'https://www.neb.com/en-us/products/n0447-deoxynucleotide-dntp-solution-mix', NULL, NULL, NULL, NULL, 'in_stock'),
 (16, 'Gibco',   '70011044',  'PBS (10X), pH 7.4',                                'reagent',  '1 L',    'bottle', 41.50,  'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F70011044_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/70011044', NULL, NULL, NULL, NULL, 'in_stock'),
 (17, 'Invitrogen', '15568025', 'Tris-HCl (1 M), pH 8.0',                         'reagent',  '1 L',    'bottle', 58.00,  'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F15568025_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/15568025', '1185-53-1', NULL, NULL, NULL, 'in_stock'),
 (18, 'Bio-Rad', '1613101',   'Certified Molecular Biology Agarose',              'reagent',  '500 g',  'box',    289.00, 'https://www.bio-rad.com/webroot/web/pdf/lsr/sds/1613101.pdf', 'https://www.bio-rad.com/en-us/sku/1613101-certified-molecular-biology-agarose', '9012-36-6', NULL, NULL, NULL, 'in_stock'),
 (19, 'Invitrogen', '16500500', 'UltraPure Agarose',                              'reagent',  '500 g',  'box',    245.00, 'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F16500500_SDS.pdf', 'https://www.thermofisher.com/order/catalog/product/16500500', '9012-36-6', NULL, NULL, NULL, 'in_stock'),
 (20, 'Millipore Sigma', 'MAB377', 'Anti-NeuN Antibody, clone A60',               'antibody', '100 uL', 'vial',   469.00, 'https://www.sigmaaldrich.com/US/en/sds/mm/mab377', 'https://www.sigmaaldrich.com/US/en/product/mm/mab377', NULL, NULL, NULL, NULL, 'in_stock'),
 (21, 'Abcam',   'ab177487',  'Anti-NeuN antibody [EPR12763]',                    'antibody', '100 uL', 'vial',   425.00, 'https://www.abcam.com/en-us/products/primary-antibodies/neun-antibody-epr12763-ab177487#support-msds', 'https://www.abcam.com/en-us/products/primary-antibodies/neun-antibody-epr12763-ab177487', NULL, NULL, NULL, NULL, 'in_stock'),
 (22, 'Agilent (Dako)', 'Z0334', 'Polyclonal Rabbit Anti-GFAP',                    'antibody', '10 mL',  'vial',   312.00, 'https://www.agilent.com/store/en_US/Prod-Z033429-2/Z0334', 'https://www.agilent.com/store/en_US/Prod-Z033429-2/Z0334', NULL, NULL, NULL, NULL, 'in_stock'),
 (23, 'Cell Signaling Technology', '12389', 'GFAP (D1F4Q) XP Rabbit mAb',         'antibody', '100 uL', 'vial',   389.00, 'https://www.cellsignal.com/products/primary-antibodies/gfap-d1f4q-xp-rabbit-mab/12389#product-support', 'https://www.cellsignal.com/products/primary-antibodies/gfap-d1f4q-xp-rabbit-mab/12389', NULL, NULL, NULL, NULL, 'in_stock'),
 (24, 'Sigma-Aldrich', 'D2650', 'Dimethyl sulfoxide (DMSO), Hybri-Max, sterile',  'chemical', '100 mL', 'bottle', 72.00,  'https://www.sigmaaldrich.com/US/en/sds/sigma/d2650', 'https://www.sigmaaldrich.com/US/en/product/sigma/d2650', '67-68-5', 'irritant', NULL, NULL, 'in_stock'),
 (25, 'Sigma-Aldrich', 'X100', 'Triton X-100',                                    'chemical', '500 mL', 'bottle', 68.50,  'https://www.sigmaaldrich.com/US/en/sds/sigma/x100', 'https://www.sigmaaldrich.com/US/en/product/sigma/x100', '9002-93-1', 'corrosive,irritant', NULL, NULL, 'in_stock'),
 (26, 'Sigma-Aldrich', 'E7023', 'Ethanol, 200 proof, anhydrous',                  'chemical', '1 L',    'bottle', 96.00,  'https://www.sigmaaldrich.com/US/en/sds/sigma/e7023', 'https://www.sigmaaldrich.com/US/en/product/sigma/e7023', '64-17-5', 'flammable,irritant', NULL, NULL, 'in_stock'),
 (27, 'Sigma-Aldrich', '179337', 'Methanol, anhydrous 99.8%',                     'chemical', '1 L',    'bottle', 58.00,  'https://www.sigmaaldrich.com/US/en/sds/sial/179337', 'https://www.sigmaaldrich.com/US/en/product/sial/179337', '67-56-1', 'flammable,toxic', NULL, NULL, 'in_stock'),
 (28, 'Electron Microscopy Sciences', '16000', 'Glutaraldehyde, 25% EM grade',    'chemical', '10 x 10 mL', 'ampule', 44.00, 'https://www.emsdiasum.com/sds/16000', 'https://www.emsdiasum.com/glutaraldehyde-25', '111-30-8', 'toxic,corrosive', NULL, NULL, 'in_stock'),
 (29, 'Sigma-Aldrich', 'A9647', 'Bovine Serum Albumin, lyophilized',              'reagent',  '100 g',  'bottle', 168.00, 'https://www.sigmaaldrich.com/US/en/sds/sigma/a9647', 'https://www.sigmaaldrich.com/US/en/product/sigma/a9647', '9048-46-8', NULL, NULL, NULL, 'in_stock'),
 (30, 'Bio-Rad', '1610747',   '4x Laemmli Sample Buffer',                         'reagent',  '10 mL',  'bottle', 96.00,  'https://www.bio-rad.com/webroot/web/pdf/lsr/sds/1610747.pdf', 'https://www.bio-rad.com/en-us/sku/1610747-4x-laemmli-sample-buffer', NULL, 'flammable,irritant', NULL, NULL, 'in_stock'),
 (31, 'Sigma-Aldrich', 'A0280', 'Anti-GABA antibody',                             'antibody', '200 uL', 'vial',   388.00, 'https://www.sigmaaldrich.com/US/en/sds/sigma/a0280', 'https://www.sigmaaldrich.com/US/en/product/sigma/a0280', NULL, NULL, NULL, NULL, 'discontinued');

-- Link existing inventory rows to the catalog product they were sourced from,
-- and enrich chemical/reagent items with GHS hazard class, CAS number, and a
-- reorder_max (the "top up to" level auto-POs fill to; ~2-3x reorder_threshold).
UPDATE inventory SET catalog_id = 1,  hazard_class = 'toxic,irritant', cas_number = '30525-89-4', reorder_max = 12 WHERE item_id = 3;  -- 4% Paraformaldehyde
UPDATE inventory SET catalog_id = 4,  reorder_max = 12 WHERE item_id = 7;   -- DMEM High Glucose
UPDATE inventory SET catalog_id = 12, reorder_max = 8  WHERE item_id = 8;   -- Fetal Bovine Serum
UPDATE inventory SET catalog_id = 10, reorder_max = 9  WHERE item_id = 9;   -- Trypsin-EDTA 0.25%
UPDATE inventory SET catalog_id = 7,  reorder_max = 6  WHERE item_id = 11;  -- Taq DNA Polymerase
UPDATE inventory SET catalog_id = 15, reorder_max = 12 WHERE item_id = 12;  -- dNTP Mix 10mM
UPDATE inventory SET catalog_id = 20, reorder_max = 4  WHERE item_id = 13;  -- Anti-NeuN antibody
UPDATE inventory SET catalog_id = 22, reorder_max = 4  WHERE item_id = 14;  -- Anti-GFAP antibody
UPDATE inventory SET catalog_id = 16, reorder_max = 15 WHERE item_id = 15;  -- PBS 10x
UPDATE inventory SET catalog_id = 17, hazard_class = 'irritant', cas_number = '1185-53-1', reorder_max = 9 WHERE item_id = 16;  -- Tris-HCl
UPDATE inventory SET catalog_id = 18, cas_number = '9012-36-6', reorder_max = 6 WHERE item_id = 17;  -- Agarose
UPDATE inventory SET catalog_id = 31 WHERE item_id = 4;   -- Anti-GABA antibody (deprecated; catalog row discontinued)

-- Chemical items without a catalog link still carry hazard metadata + top-up level.
UPDATE inventory SET hazard_class = 'irritant', cas_number = '26675-46-7', reorder_max = 8 WHERE item_id = 1;  -- Isoflurane
UPDATE inventory SET hazard_class = 'toxic',    cas_number = '6740-88-1',  reorder_max = 6 WHERE item_id = 2;  -- Ketamine
UPDATE inventory SET reorder_max = 12 WHERE item_id = 18;  -- Nitrile gloves M

-- Point the lot-level CoA links at the representative sample CoA files shipped
-- in examples/coa/ (real CoAs are lot-specific and not published publicly).
UPDATE item_lot SET coa_url = 'examples/coa/fbs-coa.html'            WHERE lot_number = 'FBS-2701';
UPDATE item_lot SET coa_url = 'examples/coa/taq-polymerase-coa.html' WHERE lot_number = 'TAQ-2612';
UPDATE item_lot SET coa_url = 'examples/coa/neun-antibody-coa.html'  WHERE lot_number = 'NEUN-2507';

-- Real manufacturer SDS URLs on the chemical/reagent items (replacing the
-- earlier illustrative example.com placeholders). These match the sds_url on
-- the linked vendor_catalog rows and the examples/sds-index.md table.
UPDATE inventory SET sds_url = 'https://www.sigmaaldrich.com/US/en/sds/aldrich/792632' WHERE item_id = 1;  -- Isoflurane (Sigma 792632)
UPDATE inventory SET sds_url = 'https://www.sigmaaldrich.com/US/en/sds/sigma/k2753'    WHERE item_id = 2;  -- Ketamine (Sigma K2753)
UPDATE inventory SET sds_url = 'https://www.sigmaaldrich.com/US/en/sds/sigma/p6148'    WHERE item_id = 3;  -- Paraformaldehyde (Sigma P6148)
UPDATE inventory SET sds_url = 'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F25200056_SDS.pdf' WHERE item_id = 9;   -- Trypsin-EDTA (Gibco 25200056)
UPDATE inventory SET sds_url = 'https://www.neb.com/-/media/nebus/files/sds/n0447_sds.pdf' WHERE item_id = 12;  -- dNTP Mix (NEB N0447)
UPDATE inventory SET sds_url = 'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F70011044_SDS.pdf' WHERE item_id = 15;  -- PBS 10x (Gibco 70011044)
UPDATE inventory SET sds_url = 'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F15568025_SDS.pdf' WHERE item_id = 16;  -- Tris-HCl (Invitrogen 15568025)
UPDATE inventory SET sds_url = 'https://www.bio-rad.com/webroot/web/pdf/lsr/sds/1613101.pdf' WHERE item_id = 17;  -- Agarose (Bio-Rad 1613101)

-- Attached documents. kind sds/coa/invoice; exactly one of item_id/lot_id/po_id
-- is set. SDS rows link the item to its real manufacturer SDS; CoA rows attach a
-- representative sample (examples/coa/*.html) to the specific lot; the invoice is
-- attached to the received Gibco PO (po_id=1). uploaded_by is a soft ref to
-- app_user(id): manager=2, member=3.
INSERT INTO item_document (id, item_id, lot_id, po_id, kind, label, url, filename, uploaded_at, uploaded_by) VALUES
 (1,  1,  NULL, NULL, 'sds', 'Isoflurane SDS (Sigma 792632)',      'https://www.sigmaaldrich.com/US/en/sds/aldrich/792632', NULL, '2026-06-15 09:20:00', 2),
 (2,  2,  NULL, NULL, 'sds', 'Ketamine HCl SDS (Sigma K2753)',     'https://www.sigmaaldrich.com/US/en/sds/sigma/k2753',    NULL, '2026-06-15 09:22:00', 2),
 (3,  3,  NULL, NULL, 'sds', 'Paraformaldehyde SDS (Sigma P6148)', 'https://www.sigmaaldrich.com/US/en/sds/sigma/p6148',    NULL, '2026-06-15 09:24:00', 2),
 (4,  9,  NULL, NULL, 'sds', 'Trypsin-EDTA SDS (Gibco 25200056)',  'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F25200056_SDS.pdf', NULL, '2026-06-15 09:26:00', 2),
 (5,  12, NULL, NULL, 'sds', 'dNTP Mix SDS (NEB N0447)',           'https://www.neb.com/-/media/nebus/files/sds/n0447_sds.pdf', NULL, '2026-06-15 09:28:00', 2),
 (6,  15, NULL, NULL, 'sds', 'PBS 10x SDS (Gibco 70011044)',       'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F70011044_SDS.pdf', NULL, '2026-06-15 09:30:00', 2),
 (7,  16, NULL, NULL, 'sds', 'Tris-HCl 1M SDS (Invitrogen 15568025)', 'https://www.thermofisher.com/document-connect/document-connect.html?url=https%3A%2F%2Fassets.thermofisher.com%2FTFS-Assets%2FLSG%2FSDS%2F15568025_SDS.pdf', NULL, '2026-06-15 09:32:00', 2),
 (8,  17, NULL, NULL, 'sds', 'Agarose SDS (Bio-Rad 1613101)',      'https://www.bio-rad.com/webroot/web/pdf/lsr/sds/1613101.pdf', NULL, '2026-06-15 09:34:00', 2),
 (9,  NULL, 9,  NULL, 'coa', 'FBS lot FBS-2701 CoA',               'examples/coa/fbs-coa.html',            NULL, '2026-05-22 11:05:00', 2),
 (10, NULL, 14, NULL, 'coa', 'Taq lot TAQ-2612 CoA',               'examples/coa/taq-polymerase-coa.html', NULL, '2026-04-01 10:12:00', 2),
 (11, NULL, 16, NULL, 'coa', 'Anti-NeuN lot NEUN-2507 CoA',        'examples/coa/neun-antibody-coa.html',  NULL, '2026-03-12 14:40:00', 3),
 (12, NULL, 4,  NULL, 'coa', 'Paraformaldehyde lot PFA-2509 CoA',  'examples/coa/paraformaldehyde-coa.html', NULL, '2026-05-02 15:18:00', 2),
 (13, NULL, 7,  NULL, 'coa', 'DMEM lot DMEM-2606 CoA',             'examples/coa/dmem-coa.html',           NULL, '2026-04-10 09:50:00', 2),
 (14, NULL, NULL, 1,  'invoice', 'Gibco invoice (media restock)',  'https://example-vendor.com/invoices/GIBCO-2026-06-15.pdf', NULL, '2026-06-15 11:30:00', 2);

-- Purchase-order approval workflow. POs 1-3 above cover received/ordered/draft;
-- these add the approval-lifecycle states so the sign-off flow is demonstrable:
--   4 pending_approval (member requested, awaiting PI sign-off)
--   5 approved         (approved_by manager=2, approved_at set; not yet submitted)
--   6 submitted        (approved then submitted to the vendor)
-- created_by / approved_by are soft refs to app_user(id): manager=2, member=3.
INSERT INTO purchase_order (id, vendor, status, created_by, created_at, approved_by, approved_at, approver_note, submitted_at, ordered_at, received_at, note) VALUES
 (4, 'Sigma-Aldrich', 'pending_approval', 3, '2026-07-02 15:40:00', NULL, NULL,                  NULL,                          NULL,                  NULL, NULL, 'Fixative + solvents restock -- awaiting PI approval'),
 (5, 'Bio-Rad',       'approved',         3, '2026-06-30 10:15:00', 2,    '2026-07-01 08:45:00', 'Approved -- within Q3 consumables budget.', NULL,                  NULL, NULL, 'Electrophoresis reagents'),
 (6, 'Invitrogen',    'submitted',        2, '2026-06-27 13:05:00', 2,    '2026-06-28 09:10:00', 'Approved for genotyping pipeline.',         '2026-06-29 10:30:00', NULL, NULL, 'Platinum Taq + Tris buffer');

INSERT INTO po_line (id, po_id, item_id, quantity, unit_cost, received_qty) VALUES
 (7,  4, 3,  6, 138.00, 0),   -- Paraformaldehyde (Sigma P6148)
 (8,  4, 16, 4, 34.50,  0),   -- Tris-HCl
 (9,  5, 17, 4, 156.00, 0),   -- Agarose (Bio-Rad)
 (10, 6, 11, 3, 168.00, 0),   -- Taq -> Platinum Taq
 (11, 6, 16, 2, 58.00,  0);   -- Tris-HCl 1M (Invitrogen)

-- =====================================================================
-- NIMBLE LAB MANAGER Wave 3 seed (batch 1): storage-compatibility demo,
-- member requisition, and the auto-approval threshold. Appended so every
-- id assigned above stays stable. 'today' for the demo is 2026-07-04.
-- =====================================================================

-- INTENTIONAL STORAGE-SEGREGATION VIOLATION (demo data for the Safety view).
-- Three items already sit together in the -80C Freezer (node 10): existing
-- containers place them in boxes on Shelf 1 (node 20) -- DMEM (item 7) and
-- Anti-NeuN (item 13) share Box A1 (node 30) and Anti-GFAP (item 14) is in
-- Box A2 (node 31), both boxes under Shelf 1. We deliberately set their
-- hazard_class so incompatible GHS pairs co-locate under one storage unit
-- WITHOUT adding any location or container rows:
--   DMEM      (item 7)  = flammable,irritant   (flammable = intentional demo)
--   Anti-NeuN (item 13) = oxidizer,irritant    (oxidizer  = intentional demo)
--   Anti-GFAP (item 14) = corrosive,irritant   (corrosive = intentional demo)
-- The compatibility scanner walks the freezer/shelf subtree and flags, at the
-- deepest storage unit that contains them (Shelf 1, node 20), the incompatible
-- pairs among {flammable, oxidizer, corrosive}:
--   flammable + oxidizer  -> DANGER (fire/explosion risk)
--   flammable + corrosive -> WARN
--   oxidizer  + corrosive -> WARN
-- These hazard-class edits add no rows and do not touch any item_lot.quantity,
-- so quantity_on_hand == SUM(item_lot.quantity) is preserved.
UPDATE inventory SET hazard_class = 'flammable,irritant' WHERE item_id = 7;   -- DMEM (flammable = intentional demo)
UPDATE inventory SET hazard_class = 'oxidizer,irritant'  WHERE item_id = 13;  -- Anti-NeuN (oxidizer = intentional demo)
UPDATE inventory SET hazard_class = 'corrosive,irritant' WHERE item_id = 14;  -- Anti-GFAP (corrosive = intentional demo)

-- Compartment storage-suitability ratings (feature: placement warnings). The map
-- shows what each compartment is rated for; an item stored somewhere unsuitable is
-- flagged. -80C Freezer and 4C Fridge get a temperature rating; the Flammables
-- Cabinet is rated for flammables only.
UPDATE location_node SET temp_rating = '-80C'      WHERE id = 10;  -- -80C Freezer
UPDATE location_node SET temp_rating = '4C'        WHERE id = 11;  -- 4C Fridge
UPDATE location_node SET allowed_hazards = 'flammable' WHERE id = 12;  -- Flammables Cabinet
-- INTENTIONAL PLACEMENT MISMATCH (demo): DMEM (item 7) is a 4C medium but sits in
-- the -80C Freezer, so the placement check flags a temperature warning.
UPDATE inventory SET storage_temp = '4C'   WHERE item_id = 7;    -- DMEM (belongs at 4C)
UPDATE inventory SET storage_temp = '-80C' WHERE item_id = 13;   -- Anti-NeuN (correctly -80C)
UPDATE inventory SET storage_temp = '-80C' WHERE item_id = 14;   -- Anti-GFAP (correctly -80C)

-- A MEMBER-created requisition: a draft purchase order owned by the member
-- (created_by = app_user 3), distinct from the manager-owned POs above. This
-- is a requisition awaiting the member's own "request approval" action.
INSERT INTO purchase_order (id, vendor, status, created_by, created_at, approved_by, approved_at, approver_note, submitted_at, ordered_at, received_at, note) VALUES
 (7, 'Fisher', 'draft', 3, '2026-07-04 09:30:00', NULL, NULL, NULL, NULL, NULL, NULL, 'Member requisition -- bench consumables');

INSERT INTO po_line (id, po_id, item_id, quantity, unit_cost, received_qty) VALUES
 (12, 7, 18, 4, 12.50, 0),    -- Nitrile gloves M
 (13, 7, 15, 2, 22.00, 0);    -- PBS 10x

-- =====================================================================
-- NIMBLE LAB MANAGER Wave 3 seed (batch 2): cycle-count / stocktake and
-- kits (bill-of-materials) demo data. 'today' for the demo is 2026-07-04.
-- =====================================================================

-- Three realistic reagent recipes (kits), built from real seeded inventory
-- items. Quantities are chosen so every kit is assemblable at least once
-- against seeded on-hand (max_assemblies = min over components of
-- floor(on_hand/quantity)). None of these produce a distinct output item
-- (they consume raw stock into a working solution, not a new catalog item),
-- so output_item_id is left NULL / output_qty 0.
INSERT INTO kit (id, name, description, output_item_id, output_qty) VALUES
 (1, '4% PFA fixative (500 mL)',
     'Working perfusion/immersion fixative diluted from stock paraformaldehyde and PBS.',
     NULL, 0),
 (2, 'Genotyping PCR master mix',
     'Standard Taq-based master mix for tail/ear-clip genotyping PCR.',
     NULL, 0),
 (3, 'Immunostaining block buffer',
     'Serum-based blocking buffer for fluorescent immunohistochemistry.',
     NULL, 0);

INSERT INTO kit_line (id, kit_id, item_id, quantity) VALUES
 (1, 1, 3,  2),   -- 4% Paraformaldehyde (on_hand 6 -> 3 assemblies)
 (2, 1, 15, 2),   -- PBS 10x             (on_hand 10 -> 5 assemblies)
 (3, 2, 11, 1),   -- Taq DNA Polymerase  (on_hand 4 -> 4 assemblies)
 (4, 2, 12, 2),   -- dNTP Mix 10mM       (on_hand 9 -> 4 assemblies)
 (5, 3, 8,  1),   -- Fetal Bovine Serum  (on_hand 3 -> 3 assemblies)
 (6, 3, 15, 3);   -- PBS 10x             (on_hand 10 -> 3 assemblies)

-- A CLOSED demo cycle count of the -80C Freezer (location_node 10) subtree.
-- Lines reference real containers already seeded under that freezer (boxes
-- 30/31/32, under shelves 20/21). Five lines are 'found' (scanned during the
-- count) and one ('Anti-GFAP antibody' in Box A2, container 37) was never
-- scanned and rolled over to 'missing' when the session was closed -- exactly
-- the /api/counts/{id}/close behavior, so the closed session's accuracy
-- (5/6 = ~83%) is below 100%. started_by/counted_by = app_user 2 (manager).
INSERT INTO count_session (id, location_id, name, status, started_by, started_at, closed_at, note) VALUES
 (1, 10, 'Q3 -80C freezer stocktake', 'closed', 2, '2026-07-03 09:00:00', '2026-07-03 10:15:00', 'Routine cycle count ahead of the Q3 audit.');

INSERT INTO count_line (id, session_id, container_id, item_id, box_name, row, col, expected, counted, status, counted_at, counted_by) VALUES
 (1, 1, 1,  13, 'Box A1 (RNA)', 1, 1, 1, 1,    'found',   '2026-07-03 09:05:00', 2),   -- Anti-NeuN antibody
 (2, 1, 3,  7,  'Box A1 (RNA)', 1, 3, 1, 1,    'found',   '2026-07-03 09:07:00', 2),   -- DMEM High Glucose
 (3, 1, 9,  7,  'Box A1 (RNA)', 2, 3, 1, 1,    'found',   '2026-07-03 09:09:00', 2),   -- DMEM High Glucose
 (4, 1, 33, 13, 'Box A2 (Abs)', 1, 1, 1, 1,    'found',   '2026-07-03 09:12:00', 2),   -- Anti-NeuN antibody
 (5, 1, 37, 14, 'Box A2 (Abs)', 1, 5, 1, NULL, 'missing', NULL,                  NULL), -- Anti-GFAP antibody: never scanned
 (6, 1, 48, 11, 'Box B1 (Enz)', 1, 1, 1, 1,    'found',   '2026-07-03 09:15:00', 2);   -- Taq DNA Polymerase

-- =====================================================================
-- NIMBLE LAB MANAGER Wave 3 seed (batch 3): equipment registry + booking +
-- maintenance/calibration, and grant/fund budget burn-down. Appended so
-- every id assigned above stays stable. 'today' for the demo is 2026-07-04.
-- =====================================================================

-- Six real-ish instruments placed at existing location_node ids: Bench 1
-- (13) / Bench 2 (14) for benchtop instruments, Room 201 (1) for the
-- freestanding freezer + biosafety cabinet. Dates are chosen so the
-- Eppendorf centrifuge (next_service_date 2026-06-20) is ALREADY PAST DUE
-- and the Sorvall centrifuge (2026-07-10) is due WITHIN 14 DAYS of the demo
-- "today" (2026-07-04) -- both fire the maintenance_due notification -- while
-- the rest sit comfortably in the future. Status is mostly 'operational';
-- the Zeiss microscope is 'maintenance' (its stage motor was just replaced).
INSERT INTO equipment (id, name, category, make_model, serial_number, location_id, status, purchase_date, service_interval_days, last_service_date, next_service_date, cleanup_url, note) VALUES
 (1, 'Microcentrifuge',      'centrifuge',        'Eppendorf 5424R',       'EP5424R-2201',  13, 'operational', '2023-02-10', 365, '2025-06-20', '2026-06-20', NULL, NULL),                                              -- PAST DUE
 (2, 'Benchtop Centrifuge',  'centrifuge',        'Thermo Sorvall ST8',    'ST8-88421',     14, 'operational', '2022-05-15', 365, '2025-07-10', '2026-07-10', NULL, NULL),                                              -- due in 6 days
 (3, 'Thermal Cycler',       'thermal cycler',    'Bio-Rad C1000 Touch',   'C1000-556723',  13, 'operational', '2021-11-01', 365, '2025-11-01', '2026-11-01', NULL, NULL),
 (4, 'Inverted Microscope',  'microscope',        'Zeiss Axio Observer 5', 'AXIO-778812',   14, 'maintenance', '2020-08-20', 180, '2026-03-18', '2026-09-14', NULL, 'Stage motor replaced; pending final calibration.'),
 (5, 'ULT Freezer',          'freezer',           'Thermo TSX600A',        'TSX600A-33210', 1,  'operational', '2019-03-12', 180, '2026-02-01', '2026-08-01', 'https://labsafety.example.edu/sop/ult-freezer-defrost-decon.pdf', NULL),
 (6, 'Biosafety Cabinet',    'biosafety cabinet', 'Baker SterilGARD e3',   'SG403-90112',   1,  'operational', '2021-01-20', 365, '2025-12-01', '2026-12-01', 'https://labsafety.example.edu/sop/bsc-decontamination.pdf', NULL);

-- Calibrated instruments: a balance (annual scale calibration) and individually
-- tracked pipettes (semiannual pipette calibration). Each pipette is its own
-- equipment row with a home location + serial, so a misplaced one can be found
-- and its calibration tracked. service_interval_days is the calibration cadence.
INSERT INTO equipment (id, name, category, make_model, serial_number, location_id, status, purchase_date, service_interval_days, last_service_date, next_service_date, cleanup_url, note) VALUES
 (8,  'Analytical Balance',    'balance',  'Mettler Toledo XPR205', 'MT-XPR205-3312', 13, 'operational', '2023-04-01', 365, '2025-07-15', '2026-07-15', NULL, 'Annual external calibration; daily internal calibration + weekly check-weight verification (200 g / 100 g).'),  -- calibration due soon
 (9,  'Pipette P1000 (#1)',    'pipette',  'Gilson PIPETMAN L P1000', 'GIL-P1000-8842', 13, 'operational', '2022-09-01', 180, '2025-12-20', '2026-06-20', NULL, 'Home: Bench 1. Air-displacement, semiannual gravimetric calibration.'),  -- calibration OVERDUE
 (10, 'Pipette P200 (#1)',     'pipette',  'Gilson PIPETMAN L P200',  'GIL-P200-8843',  13, 'operational', '2022-09-01', 180, '2026-02-14', '2026-08-13', NULL, 'Home: Bench 1. Return to the pipette carousel after use.'),
 (11, 'Pipette P20 (#1)',      'pipette',  'Gilson PIPETMAN L P20',   'GIL-P20-8844',   14, 'operational', '2022-09-01', 180, '2026-01-20', '2026-07-19', NULL, 'Home: Bench 2. Return to the pipette carousel after use.'),  -- calibration due soon
 (12, 'Pipette P1000 (#2)',    'pipette',  'Gilson PIPETMAN L P1000', 'GIL-P1000-9017', 14, 'operational', '2023-05-10', 180, '2026-03-01', '2026-08-28', NULL, 'Home: Bench 2. Shared cell-culture pipette.'),
 (13, 'Multichannel P300 (8-ch)','pipette','Eppendorf Research 8-ch', 'EP-8CH-5521',    13, 'operational', '2024-02-01', 180, '2026-01-25', '2026-07-24', NULL, 'Home: Bench 1, ELISA station. 8-channel; calibrate all channels.');  -- calibration due soon

-- Upcoming bookings (member=3 / manager=2), non-overlapping across time and
-- equipment.
INSERT INTO equipment_reservation (id, equipment_id, user_id, starts_at, ends_at, purpose, created_at) VALUES
 (1, 1, 3, '2026-07-09 09:00:00', '2026-07-09 10:00:00', 'Serum separation for cell culture prep', '2026-07-05 08:15:00'),
 (2, 3, 3, '2026-07-10 13:00:00', '2026-07-10 16:00:00', 'Genotyping PCR run for cohort B',         '2026-07-05 08:20:00'),
 (3, 4, 2, '2026-07-11 10:00:00', '2026-07-11 12:00:00', 'Imaging fixed sections for Aim 2',        '2026-07-06 09:00:00'),
 (4, 1, 2, '2026-07-14 08:00:00', '2026-07-14 09:30:00', 'Plasma spin-down',                        '2026-07-06 09:05:00'),
 (5, 6, 3, '2026-07-15 09:00:00', '2026-07-15 12:00:00', 'Sterile media prep',                      '2026-07-06 09:10:00');

-- Past service records. performed_at/next_due for equipment 1/2/4 match the
-- last_service_date/next_service_date set on the equipment rows above.
INSERT INTO equipment_maintenance (id, equipment_id, kind, performed_at, performed_by, note, next_due) VALUES
 (1, 1, 'preventive',   '2025-06-20', 'A. Rivera',              'Annual PM: rotor inspection, brush replacement.',                     '2026-06-20'),
 (2, 1, 'calibration',  '2024-06-18', 'Eppendorf Field Service', 'Speed calibration verified within spec.',                             '2025-06-20'),
 (3, 2, 'preventive',   '2025-07-10', 'J. Chen',                 'Annual PM: door seal + rotor check.',                                 '2026-07-10'),
 (4, 4, 'repair',       '2026-03-18', 'Zeiss Field Engineer',    'Replaced stage motor; returned to service pending final calibration.', '2026-09-14'),
 (5, 8,  'calibration', '2025-07-15', 'Mettler Toledo Service',  'Annual scale calibration; passed at all test loads (10 mg - 200 g).',   '2026-07-15'),
 (6, 8,  'calibration', '2026-07-01', 'A. Rivera',               'Weekly check-weight verification (200 g / 100 g) within tolerance.',     NULL),
 (7, 9,  'calibration', '2025-12-20', 'PipetteCal Services',     'Semiannual gravimetric calibration; P1000 within spec at 100/500/1000 uL.', '2026-06-20'),
 (8, 10, 'calibration', '2026-02-14', 'PipetteCal Services',     'Semiannual gravimetric calibration; P200 passed.',                      '2026-08-13'),
 (9, 11, 'calibration', '2026-01-20', 'PipetteCal Services',     'Semiannual gravimetric calibration; P20 adjusted, now in tolerance.',    '2026-07-19'),
 (10, 13,'calibration', '2026-01-25', 'Eppendorf Field Service', 'All 8 channels calibrated; channel 5 seal replaced.',                    '2026-07-24');

-- Three grants: an NIH R01, an NSF award, and an internal PI startup fund.
INSERT INTO fund (id, name, sponsor, budget, start_date, end_date, note) VALUES
 (1, 'R01-NS118273',                'NIH',      250000.00, '2024-09-01', '2029-08-31', 'Rodent models of cognitive decline -- primary R01.'),
 (2, 'NSF-IOS-2145589',             'NSF',      180000.00, '2025-01-01', '2027-12-31', 'Environmental enrichment behavioral assays.'),
 (3, 'Startup Fund -- PI Lab Launch', 'internal', 50000.00, '2024-01-01', '2026-12-31', 'Institutional startup package for new PI lab.');

-- Charges against each fund: a mix of received-PO pass-throughs, manual
-- entries, and ticket-linked reagent draws. charged_by = manager (2).
-- Fund 1 (R01) spent 28470.50 / 250000 = ~11.4%; Fund 2 (NSF) spent
-- 77438.00 / 180000 = ~43.0%; Fund 3 (Startup) spent 45060.00 / 50000 =
-- ~90.1% -- intentionally near the burn-down bar's danger threshold, with
-- remaining (4940.00) still positive.
INSERT INTO fund_charge (id, fund_id, amount, source_type, source_id, description, charged_at, charged_by) VALUES
 (1,  1, 728.00,   'purchase_order', 1,    'PO #1 (Gibco)',                                  '2026-06-16 09:10:00', 2),
 (2,  1, 18500.00, 'manual',         NULL, 'Postdoc salary support -- Q2 effort',            '2026-06-20 10:00:00', 2),
 (3,  1, 9200.00,  'manual',         NULL, 'Core imaging facility fees',                      '2026-06-25 14:30:00', 2),
 (4,  1, 42.50,    'ticket',         1,    'Ticket #1 (Perfusion) reagent draw',              '2026-06-22 09:45:00', 2),
 (5,  2, 62000.00, 'manual',         NULL, 'Behavioral core -- equipment time-share buyout',  '2026-05-05 11:00:00', 2),
 (6,  2, 15400.00, 'manual',         NULL, 'Animal per-diem charges Q2',                      '2026-06-01 09:30:00', 2),
 (7,  2, 38.00,    'ticket',         4,    'Ticket #4 (Immunostaining) reagent draw',         '2026-06-29 14:20:00', 2),
 (8,  3, 21000.00, 'manual',         NULL, 'Lab equipment down payment (thermal cycler)',     '2026-02-10 10:00:00', 2),
 (9,  3, 15500.00, 'manual',         NULL, 'Startup reagent stock-up',                        '2026-03-15 09:00:00', 2),
 (10, 3, 8500.00,  'manual',         NULL, 'Publication + conference costs',                  '2026-04-20 13:00:00', 2),
 (11, 3, 60.00,    'ticket',         7,    'Ticket #7 (Perfusion) reagent draw',               '2026-07-03 10:15:00', 2);

-- =====================================================================
-- NIMBLE LAB MANAGER Wave 4 seed: preparations (in-house mixes), lab
-- maintenance chores, and purchasing fund/ETA. Appended so every id
-- assigned above stays stable. 'today' for the demo is 2026-07-04.
-- =====================================================================

-- Four real in-house-mix recipes, built from real seeded inventory items:
-- PBS 1x (diluted from PBS 10x, item 15), fresh 4% PFA (Paraformaldehyde,
-- item 3 + PBS 10x), aCSF (component surrogate from Tris-HCl + PBS -- no
-- true aCSF salts are seeded), and an FBS-based blocking buffer. Quantities
-- are chosen so every recipe is assemblable against seeded on-hand
-- (PFA on_hand 6 -> 3 assemblies; PBS on_hand 10 -> 10; Tris-HCl on_hand 7;
-- FBS on_hand 3).
INSERT INTO preparation (id, name, description, category, shelf_life_days, sop_url, note) VALUES
 (1, 'PBS 1x',
     '1x phosphate-buffered saline diluted from 10x stock.',
     'buffer', 30, 'https://protocols.example.edu/sop/pbs-1x-dilution.pdf', NULL),
 (2, '4% PFA (fresh)',
     'Fresh 4% paraformaldehyde fixative made up from stock and PBS.',
     'fixative', 7, 'https://protocols.example.edu/sop/pfa-4pct-fixative.pdf', NULL),
 (3, 'aCSF',
     'Artificial cerebrospinal fluid (component surrogate from buffer stock; no true aCSF salts in the seeded inventory).',
     'buffer', 3, NULL, NULL),
 (4, 'Blocking buffer',
     'FBS-based blocking buffer for fluorescent immunostaining.',
     'buffer', 14, NULL, NULL);

INSERT INTO preparation_line (id, preparation_id, item_id, quantity) VALUES
 (1, 1, 15, 1),   -- PBS 1x: PBS 10x
 (2, 2, 3,  2),   -- 4% PFA: 4% Paraformaldehyde
 (3, 2, 15, 1),   -- 4% PFA: PBS 10x
 (4, 3, 16, 1),   -- aCSF: Tris-HCl 1M pH 8.0
 (5, 3, 15, 1),   -- aCSF: PBS 10x
 (6, 4, 8,  1),   -- Blocking buffer: Fetal Bovine Serum
 (7, 4, 15, 1);   -- Blocking buffer: PBS 10x

-- Five batches across the four preps. made_by is manager (2) or member (3);
-- expiry_date = made_at + shelf_life_days. Batch 2 (4% PFA, PFA4-2625A) is
-- ALREADY EXPIRED (expiry 2026-07-02, two days before "today"); batch 1
-- (PBS 1x, PBS-2606A) is EXPIRING SOON (expiry 2026-07-05, one day out); the
-- rest are comfortably fresh. All start 'in_use'.
INSERT INTO preparation_batch (id, preparation_id, lot_label, made_by, made_at, expiry_date, amount, status, note) VALUES
 (1, 1, 'PBS-2606A',   3, '2026-06-05 09:10:00', '2026-07-05', '1 L',    'in_use', NULL),  -- expiring soon
 (2, 2, 'PFA4-2625A',  2, '2026-06-25 10:30:00', '2026-07-02', '500 mL', 'in_use', NULL),  -- EXPIRED
 (3, 2, 'PFA4-2703A',  3, '2026-07-03 14:00:00', '2026-07-10', '500 mL', 'in_use', NULL),
 (4, 3, 'ACSF-2704A',  2, '2026-07-04 08:00:00', '2026-07-07', '200 mL', 'in_use', NULL),
 (5, 4, 'BLK-2630A',   3, '2026-06-30 11:00:00', '2026-07-14', '300 mL', 'in_use', NULL);

-- Six recurring lab-maintenance chores at real location_node ids (Room 201
-- Wet Lab = 1, Vivarium = 2, -80C Freezer = 10, Bench 1 = 13). "Clean
-- biosafety cabinet" is OVERDUE (next_due 2026-07-02, two days before
-- "today"); "Defrost -80C backup" is badly OVERDUE (next_due 2026-06-20,
-- an annual task that slipped); "Autoclave biohazard waste" is DUE SOON
-- (next_due 2026-07-06); the rest sit comfortably in the future.
INSERT INTO chore (id, name, category, location_id, interval_days, last_done, next_due, instructions, note) VALUES
 (1, 'Clean biosafety cabinet',    'cleaning',    1,  7,   '2026-06-25', '2026-07-02',
     'Wipe down the work surface with 70% ethanol; run a 15-minute UV cycle.', NULL),   -- OVERDUE
 (2, 'Autoclave biohazard waste',  'autoclave',   1,  3,   '2026-07-03', '2026-07-06',
     'Autoclave biohazard bags at 121C for 30 minutes; log the cycle.', NULL),          -- due soon
 (3, 'Fill DI water tank',         'water',       1,  7,   '2026-07-01', '2026-07-08',
     'Top off the DI water reservoir from the house line; check conductivity.', NULL),
 (4, 'Calibrate pipettes',         'calibration', 13, 180, '2026-01-15', '2026-07-14',
     'Send single-channel pipettes out for gravimetric calibration.', NULL),
 (5, 'Empty sharps containers',    'stocking',    2,  14,  '2026-07-01', '2026-07-15',
     'Seal full sharps containers, replace them, and log the pickup.', NULL),
 (6, 'Defrost -80C backup',        'other',       10, 365, '2025-06-20', '2026-06-20',
     'Defrost and clean the backup ULT freezer; verify alarm wiring.', NULL);           -- OVERDUE

INSERT INTO chore_log (id, chore_id, done_by, done_at, note) VALUES
 (1, 1, 3, '2026-06-25 14:20:00', 'Wiped down cabinet, UV cycle run.'),
 (2, 2, 2, '2026-07-03 16:10:00', 'Autoclave cycle completed, waste bagged.'),
 (3, 6, 2, '2025-06-20 10:00:00', 'Manual defrost + backup transfer completed.');

-- Funding source + expected arrival on the existing ordered/submitted POs.
-- PO 2 (NEB, ordered 2026-06-29) is given an expected_arrival of 2026-07-02
-- -- two days PAST DUE vs "today" (2026-07-04), demonstrating a late
-- shipment; PO 6 (Invitrogen, submitted 2026-06-29) gets a still-pending
-- 2026-07-10 arrival. fund_id links each to a seeded grant.
UPDATE purchase_order SET fund_id = 1, expected_arrival = '2026-07-02' WHERE id = 2;  -- R01-NS118273
UPDATE purchase_order SET fund_id = 2, expected_arrival = '2026-07-10' WHERE id = 6;  -- NSF-IOS-2145589

-- =====================================================================
-- WAVE 5 DEMO: office supplies (inventory category) + a serviced printer,
-- Computers/IT assets + software licenses, and glassware with check-outs.
-- =====================================================================

-- Office supplies as ordinary inventory items (category 'office').
INSERT INTO inventory (item_id, item_name, vendor, unit, quantity_on_hand, reorder_threshold, unit_cost, category, sds_url) VALUES
 (200, 'Printer paper (A4, ream)', 'Staples',  'ream', 12, 6,  4.50, 'office', NULL),
 (201, 'Toner cartridge (HP 26A)', 'HP',       'each',  1, 2, 89.00, 'office', NULL),
 (202, 'Nitrile-free note pads',   'Uline',    'pad',   8, 4,  2.25, 'office', NULL);

-- The shared printer is lab hardware with a service schedule (Equipment).
INSERT INTO equipment (id, name, category, make_model, serial_number, location_id, status, purchase_date, service_interval_days, last_service_date, next_service_date, cleanup_url, note) VALUES
 (7, 'Office Laser Printer', 'printer', 'HP LaserJet M507', 'HPM507-4471', 14, 'operational', '2023-09-01', 180, '2026-05-01', '2026-11-01', NULL, 'Shared lab/office printer; toner tracked in inventory.');

-- Computers / IT hardware register.
INSERT INTO it_asset (id, name, kind, make_model, serial_number, location_id, assigned_to, purchase_date, warranty_end, status, note) VALUES
 (1, 'Imaging Workstation', 'desktop', 'Dell Precision 5860', 'DP5860-2201', 13, 2, '2024-02-15', '2027-02-15', 'in_service', 'Drives the confocal capture station.'),
 (2, 'Lab Data Server',      'server',  'Dell PowerEdge R760', 'PER760-8890', 1,  1, '2023-06-01', '2026-08-01', 'in_service', 'NAS + analysis pipelines; warranty ending soon.'),
 (3, 'Bench Laptop',         'laptop',  'Lenovo ThinkPad T14', 'TPT14-5521',  14, 3, '2022-11-10', '2025-11-10', 'in_service', 'Out of warranty; shared bench use.'),
 (4, 'Office Laser Printer', 'printer', 'HP LaserJet M507',    'HPM507-4471', 14, NULL, '2023-09-01', '2026-09-01', 'in_service', 'Same unit as Equipment #7; tracked here for IT.');

-- Software licenses (one expiring within 30 days of the 2026-07 demo window).
INSERT INTO software_license (id, name, vendor, product_code, seats, assigned_asset_id, expiry_date, annual_cost, server_cost, note) VALUES
 (1, 'GraphPad Prism',        'Dotmatics', 'PRISM-LAB-2026', 10, NULL, '2026-07-28', 1450.00, 0.00,   'Site license; renews annually -- EXPIRING SOON.'),
 (2, 'MATLAB + toolboxes',    'MathWorks', 'ML-ACAD-77213',  5,  1,    '2027-01-15', 2200.00, 0.00,   'Academic; assigned to the imaging workstation.'),
 (3, 'Electronic Lab Notebook', 'SciNote', 'SN-CLOUD-4402',  25, 2,    '2026-12-01', 3600.00, 1200.00, 'Cloud ELN; annual + hosting/server cost.');

-- Glassware / dishware pieces (home locations under the Wet Lab benches).
INSERT INTO glassware_item (id, name, kind, identifier, location_id, status, note) VALUES
 (1, '1 L Erlenmeyer flask #3', 'flask',     'GL-0003', 13, 'checked_out', NULL),
 (2, '500 mL beaker #7',        'beaker',    'GL-0007', 13, 'checked_out', NULL),
 (3, '2 L media bottle #1',     'bottle',    'GL-0011', 14, 'available',   NULL),
 (4, '250 mL graduated cyl. #2','graduated', 'GL-0020', 14, 'available',   NULL),
 (5, 'Glass petri dish set A',  'dish',      'GL-0031', 13, 'broken',      'Chipped lid -- pending disposal.');

-- Open check-outs (returned_at NULL). One is overdue vs the 2026-07-10 demo date.
INSERT INTO glassware_checkout (id, glassware_id, user_id, checked_out_at, due_at, returned_at, purpose, note) VALUES
 (1, 1, 3, '2026-07-06 10:00:00', '2026-07-08 17:00:00', NULL, 'Bacterial culture prep', NULL),  -- OVERDUE
 (2, 2, 2, '2026-07-09 14:30:00', '2026-07-14 17:00:00', NULL, 'Buffer make-up',         NULL),
 (3, 3, 3, '2026-06-20 09:00:00', '2026-06-25 17:00:00', '2026-06-24 16:10:00', 'Autoclave run', NULL);  -- returned (history)

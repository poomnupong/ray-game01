# Wildwood Keep design

The game is an **Experience** surface: original voxel scenery is the content,
and a compact field console leaves the centre of the view free for aiming.
Players use two thumbs on a tablet in portrait or landscape.

## Visual language

The interface uses the complete Clawpilot light/dark token set in
`public/style.css`. Panels use neutral surfaces and borders; rose is the primary
action/selection accent; success, warning, and danger indicate survival state.
The original 3D palette derives from those same tokens, mixing forest green,
earth, rock, water, and warden colors rather than referencing external textures.
Geometry is deliberately cuboid, with lit face shading and small deterministic
terrain color variation. Creature silhouettes, horns, wings, and tails distinguish
species; bosses are substantially larger.

Typography uses Segoe UI/Aptos/Calibri and platform fallbacks. The lobby title is
heavy and compact; gameplay labels prioritize readability over ornament.
Buttons use 10px corners, panels 16px, and spacing follows a 4px rhythm.

## Layout and interaction

The lobby is a short room chooser over a forest panorama, not a marketing page.
The play HUD has vitals and connection state above, movement at lower left,
actions at lower right, and quick slots between them. Portrait layout lifts the
thumb controls to keep the quick slots unobstructed. The centre crosshair,
block/creature label, nearby boss meter, and telegraphed warning explain immediate
consequences. Inventory, crafting, and help use a scrollable native dialog:
opening it protects focus and stops that player's movement without pausing friends.

Independent captured pointers own joystick, look, rise, and held actions.
Cancellation, focus loss, backgrounding, modal entry, and disconnection reset input.
Room selection and nearby-scout sharing use buttons, never required text input.
Errors use explicit notices; disconnected controls disable. Crafting lists real
available/required quantities and disables recipes with missing supplies.

## Rendering and verification

Terrain is 8×8 horizontal chunks with internal faces omitted and view-frustum
culling. Edits rebuild only touched chunks and boundary neighbours. Device pixel
ratio is capped at 1.5 and antialiasing/shadows are disabled for tablet cost.
Remote actors and the camera interpolate authoritative snapshots.

Chromium touch-emulated landscape and portrait captures validate the composition,
control bounds and non-overlap. Physical tablet/Safari performance is not yet
measured. Reduced-motion preference disables interface transitions.

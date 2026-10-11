package net.archivar.client;

import net.archivar.network.ArchivarPayloads;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.minecraft.ChatFormatting;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.CraftingInput;
import net.minecraft.world.item.crafting.CraftingRecipe;
import net.minecraft.world.item.crafting.RecipeHolder;
import net.minecraft.world.item.crafting.RecipeType;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;

public class ArchivarTerminalScreen extends Screen {
    private final List<ArchivarPayloads.ItemEntry> rawItems;
    private final List<ItemStack> craftGrid = new ArrayList<>();
    private List<ArchivarPayloads.ItemEntry> filteredItems = new ArrayList<>();
    private ItemStack craftResultPreview = ItemStack.EMPTY;

    private EditBox searchBox;
    private int scrollOffset = 0;
    private boolean sortByCount = true;

    // GUI Dimensionen (Perfekt aufgeteilte Zonen gegen jegliche Überlappung)
    private static final int GUI_WIDTH = 224;
    private static final int GUI_HEIGHT = 260;

    private static final int COLS = 9;
    private static final int STORAGE_ROWS = 4;
    private static final int SLOT_SIZE = 18;

    // Farbpalette
    private static final int BG_PANEL = 0xF510141C;
    private static final int BG_HEADER = 0xFF0A0D12;
    private static final int BORDER_OUTER = 0xFF00E5FF;
    private static final int BORDER_INNER = 0xFF1E2838;
    private static final int SLOT_BG = 0xFF141A24;
    private static final int SLOT_SHADOW = 0xFF070A0F;
    private static final int SLOT_HIGHLIGHT = 0xFF263245;
    private static final int HOVER_GLOW = 0x4400E5FF;
    private static final int RESULT_SLOT_GLOW = 0x3300E5FF;

    public ArchivarTerminalScreen(List<ArchivarPayloads.ItemEntry> items, List<ItemStack> craftGrid) {
        super(Component.literal("Archivar Terminal"));
        this.rawItems = new ArrayList<>(items);
        this.craftGrid.addAll(craftGrid);
        while (this.craftGrid.size() < 9) {
            this.craftGrid.add(ItemStack.EMPTY);
        }
    }

    public void updateData(List<ArchivarPayloads.ItemEntry> items, List<ItemStack> craftGrid) {
        this.rawItems.clear();
        this.rawItems.addAll(items);
        this.craftGrid.clear();
        this.craftGrid.addAll(craftGrid);
        while (this.craftGrid.size() < 9) {
            this.craftGrid.add(ItemStack.EMPTY);
        }
        filterAndSort();
        updateCraftPreview();
    }

    @Override
    protected void init() {
        int left = (this.width - GUI_WIDTH) / 2;
        int top = (this.height - GUI_HEIGHT) / 2;

        // ZONE 1: HEADER CONTROLS
        this.searchBox = new EditBox(this.font, left + 10, top + 17, 105, 12, Component.literal(""));
        this.searchBox.setBordered(false);
        this.searchBox.setTextColor(0xFFFFFF);
        this.searchBox.setResponder(text -> {
            this.scrollOffset = 0;
            filterAndSort();
        });
        this.addRenderableWidget(this.searchBox);

        // Sortier-Button
        this.addRenderableWidget(Button.builder(Component.literal(sortByCount ? "# Menge" : "A-Z"), btn -> {
            sortByCount = !sortByCount;
            btn.setMessage(Component.literal(sortByCount ? "# Menge" : "A-Z"));
            filterAndSort();
        }).bounds(left + 120, top + 14, 46, 16).build());

        // [Leeren] Button für Crafting-Gitter
        this.addRenderableWidget(Button.builder(Component.literal("Leeren"), btn -> {
            ClientPlayNetworking.send(new ArchivarPayloads.ClearCraftGridPayload());
        }).bounds(left + 168, top + 14, 46, 16).build());

        filterAndSort();
        updateCraftPreview();
    }

    private void filterAndSort() {
        String query = searchBox != null ? searchBox.getValue().toLowerCase().trim() : "";
        filteredItems = rawItems.stream()
                .filter(e -> query.isEmpty() || e.stack().getHoverName().getString().toLowerCase().contains(query))
                .sorted(sortByCount
                        ? Comparator.comparingLong(ArchivarPayloads.ItemEntry::count).reversed()
                        : Comparator.comparing(e -> e.stack().getHoverName().getString()))
                .toList();
    }

    private void updateCraftPreview() {
        if (this.minecraft == null || this.minecraft.level == null) return;
        CraftingInput input = CraftingInput.of(3, 3, this.craftGrid);
        Optional<RecipeHolder<CraftingRecipe>> match = this.minecraft.level.getRecipeManager()
                .getRecipeFor(RecipeType.CRAFTING, input, this.minecraft.level);

        if (match.isPresent()) {
            this.craftResultPreview = match.get().value().assemble(input, this.minecraft.level.registryAccess());
        } else {
            this.craftResultPreview = ItemStack.EMPTY;
        }
    }

    @Override
    public boolean mouseScrolled(double mouseX, double mouseY, double horizontalAmount, double verticalAmount) {
        int maxRows = (int) Math.ceil((double) filteredItems.size() / COLS);
        if (maxRows > STORAGE_ROWS) {
            if (verticalAmount < 0 && scrollOffset < maxRows - STORAGE_ROWS) {
                scrollOffset++;
                return true;
            } else if (verticalAmount > 0 && scrollOffset > 0) {
                scrollOffset--;
                return true;
            }
        }
        return super.mouseScrolled(mouseX, mouseY, horizontalAmount, verticalAmount);
    }

    @Override
    public boolean mouseClicked(double mouseX, double mouseY, int button) {
        int left = (this.width - GUI_WIDTH) / 2;
        int top = (this.height - GUI_HEIGHT) / 2;

        // 1. KLICK AUF ARCHIV-SLOTS (Zone 2: Y = 34..106)
        int gridX = left + 8;
        int gridY = top + 34;
        for (int r = 0; r < STORAGE_ROWS; r++) {
            for (int c = 0; c < COLS; c++) {
                int sx = gridX + c * SLOT_SIZE;
                int sy = gridY + r * SLOT_SIZE;
                if (mouseX >= sx && mouseX < sx + SLOT_SIZE && mouseY >= sy && mouseY < sy + SLOT_SIZE) {
                    int index = (scrollOffset + r) * COLS + c;
                    if (index >= 0 && index < filteredItems.size()) {
                        ArchivarPayloads.ItemEntry entry = filteredItems.get(index);
                        int amount = (button == 1) ? 1 : (hasShiftDown() ? 64 : entry.stack().getMaxStackSize());
                        ClientPlayNetworking.send(new ArchivarPayloads.ExtractItemPayload(entry.stack(), amount));
                        return true;
                    }
                }
            }
        }

        // 2. KLICK AUF 3x3 CRAFTING MATRIX (Zone 3: Y = 112..166)
        int craftX = left + 46;
        int craftY = top + 112;
        for (int r = 0; r < 3; r++) {
            for (int c = 0; c < 3; c++) {
                int sx = craftX + c * SLOT_SIZE;
                int sy = craftY + r * SLOT_SIZE;
                if (mouseX >= sx && mouseX < sx + SLOT_SIZE && mouseY >= sy && mouseY < sy + SLOT_SIZE) {
                    int slotIndex = r * 3 + c;
                    ClientPlayNetworking.send(new ArchivarPayloads.ClickCraftSlotPayload(slotIndex, button, hasShiftDown()));
                    return true;
                }
            }
        }

        // 3. KLICK AUF CRAFTING ERGEBNIS-SLOT (Zone 3: Y = 130)
        int resultX = left + 144;
        int resultY = top + 130;
        if (mouseX >= resultX && mouseX < resultX + SLOT_SIZE && mouseY >= resultY && mouseY < resultY + SLOT_SIZE) {
            if (!this.craftResultPreview.isEmpty()) {
                ClientPlayNetworking.send(new ArchivarPayloads.TakeCraftResultPayload(hasShiftDown()));
                return true;
            }
        }

        // 4. SHIFT-KLICK AUF SPIELER-INVENTAR (Zone 4: Y = 180..252)
        if (hasShiftDown() && this.minecraft != null && this.minecraft.player != null) {
            int invX = left + 31;
            int invY = top + 180;

            // Hauptinventar
            for (int r = 0; r < 3; r++) {
                for (int c = 0; c < 9; c++) {
                    int sx = invX + c * SLOT_SIZE;
                    int sy = invY + r * SLOT_SIZE;
                    if (mouseX >= sx && mouseX < sx + SLOT_SIZE && mouseY >= sy && mouseY < sy + SLOT_SIZE) {
                        int slotIndex = 9 + r * 9 + c;
                        ClientPlayNetworking.send(new ArchivarPayloads.InsertItemPayload(slotIndex));
                        return true;
                    }
                }
            }

            // Hotbar
            int hotbarY = top + 238;
            for (int c = 0; c < 9; c++) {
                int sx = invX + c * SLOT_SIZE;
                if (mouseX >= sx && mouseX < sx + SLOT_SIZE && mouseY >= hotbarY && mouseY < hotbarY + SLOT_SIZE) {
                    ClientPlayNetworking.send(new ArchivarPayloads.InsertItemPayload(c));
                    return true;
                }
            }
        }

        return super.mouseClicked(mouseX, mouseY, button);
    }

    @Override
    public void render(GuiGraphics graphics, int mouseX, int mouseY, float partialTick) {
        super.render(graphics, mouseX, mouseY, partialTick);

        int left = (this.width - GUI_WIDTH) / 2;
        int top = (this.height - GUI_HEIGHT) / 2;

        // 1. HAUPT-CHASSIS RAHMEN
        graphics.fill(left, top, left + GUI_WIDTH, top + GUI_HEIGHT, BG_PANEL);
        graphics.fill(left, top, left + GUI_WIDTH, top + 1, BORDER_OUTER);
        graphics.fill(left, top + GUI_HEIGHT - 1, left + GUI_WIDTH, top + GUI_HEIGHT, BORDER_OUTER);
        graphics.fill(left, top, left + 1, top + GUI_HEIGHT, BORDER_OUTER);
        graphics.fill(left + GUI_WIDTH - 1, top, left + GUI_WIDTH, top + GUI_HEIGHT, BORDER_OUTER);

        // Header Leiste
        graphics.fill(left + 4, top + 4, left + GUI_WIDTH - 4, top + 32, BG_HEADER);
        graphics.drawString(this.font, Component.literal("§bARCHIVAR §7| Crafting Terminal"), left + 8, top + 6, 0xFFFFFF);

        // Suchfeld-Rahmen
        graphics.fill(left + 8, top + 15, left + 116, top + 29, 0xFF000000);
        graphics.fill(left + 7, top + 14, left + 117, top + 15, BORDER_INNER);
        graphics.fill(left + 7, top + 29, left + 117, top + 30, BORDER_INNER);

        // 2. ARCHIV GRID (4 Reihen x 9 Spalten = 36 Slots)
        int gridX = left + 8;
        int gridY = top + 34;
        ItemStack hoveredStack = ItemStack.EMPTY;
        long hoveredCount = 0;

        for (int r = 0; r < STORAGE_ROWS; r++) {
            for (int c = 0; c < COLS; c++) {
                int sx = gridX + c * SLOT_SIZE;
                int sy = gridY + r * SLOT_SIZE;
                boolean isHovered = mouseX >= sx && mouseX < sx + SLOT_SIZE && mouseY >= sy && mouseY < sy + SLOT_SIZE;

                drawBeveledSlot(graphics, sx, sy, isHovered);

                int index = (scrollOffset + r) * COLS + c;
                if (index < filteredItems.size()) {
                    ArchivarPayloads.ItemEntry entry = filteredItems.get(index);
                    graphics.renderItem(entry.stack(), sx + 1, sy + 1);

                    String countText = formatCount(entry.count());
                    graphics.drawString(this.font, countText, sx + 2, sy + 9, 0xFFFFFF, true);

                    if (isHovered) {
                        hoveredStack = entry.stack();
                        hoveredCount = entry.count();
                    }
                }
            }
        }

        // Scrollbar rechts
        int scrollBarX = left + 172;
        int scrollBarY = gridY;
        int scrollBarHeight = STORAGE_ROWS * SLOT_SIZE;
        graphics.fill(scrollBarX, scrollBarY, scrollBarX + 10, scrollBarY + scrollBarHeight, 0xFF080B10);

        int maxRows = (int) Math.ceil((double) filteredItems.size() / COLS);
        int thumbHeight = maxRows > STORAGE_ROWS ? Math.max(14, (STORAGE_ROWS * scrollBarHeight) / maxRows) : scrollBarHeight;
        int thumbY = maxRows > STORAGE_ROWS ? scrollBarY + (scrollOffset * (scrollBarHeight - thumbHeight)) / (maxRows - STORAGE_ROWS) : scrollBarY;
        graphics.fill(scrollBarX + 1, thumbY + 1, scrollBarX + 9, thumbY + thumbHeight - 1, BORDER_OUTER);

        // 3. TRENNLINIE 1
        graphics.fill(left + 6, top + 107, left + GUI_WIDTH - 6, top + 108, BORDER_INNER);

        // 4. 3x3 CRAFTING MATRIX + RESULTAT
        graphics.drawString(this.font, Component.literal("§bCrafting"), left + 8, top + 112, 0x00E5FF);
        int craftX = left + 46;
        int craftY = top + 112;

        for (int r = 0; r < 3; r++) {
            for (int c = 0; c < 3; c++) {
                int sx = craftX + c * SLOT_SIZE;
                int sy = craftY + r * SLOT_SIZE;
                boolean isHovered = mouseX >= sx && mouseX < sx + SLOT_SIZE && mouseY >= sy && mouseY < sy + SLOT_SIZE;

                drawBeveledSlot(graphics, sx, sy, isHovered);

                int slot = r * 3 + c;
                if (slot < this.craftGrid.size() && !this.craftGrid.get(slot).isEmpty()) {
                    ItemStack st = this.craftGrid.get(slot);
                    graphics.renderItem(st, sx + 1, sy + 1);
                    graphics.renderItemDecorations(this.font, st, sx + 1, sy + 1);
                    if (isHovered) hoveredStack = st;
                }
            }
        }

        // Crafting Pfeil
        graphics.drawString(this.font, Component.literal("➔"), left + 116, top + 134, 0x00E5FF);

        // Ergebnis-Slot
        int resultX = left + 144;
        int resultY = top + 130;
        boolean resultHovered = mouseX >= resultX && mouseX < resultX + SLOT_SIZE && mouseY >= resultY && mouseY < resultY + SLOT_SIZE;

        drawBeveledSlot(graphics, resultX, resultY, resultHovered);
        graphics.fill(resultX + 1, resultY + 1, resultX + 17, resultY + 17, RESULT_SLOT_GLOW);

        if (!this.craftResultPreview.isEmpty()) {
            graphics.renderItem(this.craftResultPreview, resultX + 1, resultY + 1);
            graphics.renderItemDecorations(this.font, this.craftResultPreview, resultX + 1, resultY + 1);
            if (resultHovered) hoveredStack = this.craftResultPreview;
        }

        // 5. TRENNLINIE 2 & INVENTAR-BESCHRIFTUNG
        graphics.fill(left + 6, top + 168, left + GUI_WIDTH - 6, top + 169, BORDER_INNER);
        graphics.drawString(this.font, Component.literal("§7Spieler-Inventar"), left + 8, top + 171, 0x888888);

        // 6. SPIELER-INVENTAR (Zentriert: X = left + 31)
        int invX = left + 31;
        int invY = top + 180;
        ItemStack invHovered = ItemStack.EMPTY;

        if (this.minecraft != null && this.minecraft.player != null) {
            // Hauptinventar (3 Reihen)
            for (int r = 0; r < 3; r++) {
                for (int c = 0; c < 9; c++) {
                    int sx = invX + c * SLOT_SIZE;
                    int sy = invY + r * SLOT_SIZE;
                    boolean isHovered = mouseX >= sx && mouseX < sx + SLOT_SIZE && mouseY >= sy && mouseY < sy + SLOT_SIZE;

                    drawBeveledSlot(graphics, sx, sy, isHovered);

                    int slot = 9 + r * 9 + c;
                    ItemStack stack = this.minecraft.player.getInventory().getItem(slot);
                    if (!stack.isEmpty()) {
                        graphics.renderItem(stack, sx + 1, sy + 1);
                        graphics.renderItemDecorations(this.font, stack, sx + 1, sy + 1);
                        if (isHovered) invHovered = stack;
                    }
                }
            }

            // Hotbar (1 Reihe)
            int hotbarY = top + 238;
            for (int c = 0; c < 9; c++) {
                int sx = invX + c * SLOT_SIZE;
                boolean isHovered = mouseX >= sx && mouseX < sx + SLOT_SIZE && mouseY >= hotbarY && mouseY < hotbarY + SLOT_SIZE;

                drawBeveledSlot(graphics, sx, hotbarY, isHovered);

                ItemStack stack = this.minecraft.player.getInventory().getItem(c);
                if (!stack.isEmpty()) {
                    graphics.renderItem(stack, sx + 1, hotbarY + 1);
                    graphics.renderItemDecorations(this.font, stack, sx + 1, hotbarY + 1);
                    if (isHovered) invHovered = stack;
                }
            }
        }

        // 7. TOOLTIPS RENDERN
        if (!hoveredStack.isEmpty()) {
            List<Component> tooltip = new ArrayList<>(Screen.getTooltipFromItem(this.minecraft, hoveredStack));
            if (hoveredCount > 0) {
                tooltip.add(Component.literal("§bGelagert: §f" + String.format("%,d", hoveredCount)).withStyle(ChatFormatting.GRAY));
            }
            graphics.renderComponentTooltip(this.font, tooltip, mouseX, mouseY);
        } else if (!invHovered.isEmpty()) {
            graphics.renderTooltip(this.font, invHovered, mouseX, mouseY);
        }
    }

    private static void drawBeveledSlot(GuiGraphics graphics, int x, int y, boolean hovered) {
        graphics.fill(x, y, x + SLOT_SIZE, y + SLOT_SIZE, SLOT_BG);
        graphics.fill(x, y, x + SLOT_SIZE, y + 1, SLOT_SHADOW);
        graphics.fill(x, y, x + 1, y + SLOT_SIZE, SLOT_SHADOW);
        graphics.fill(x, y + SLOT_SIZE - 1, x + SLOT_SIZE, y + SLOT_SIZE, SLOT_HIGHLIGHT);
        graphics.fill(x + SLOT_SIZE - 1, y, x + SLOT_SIZE, y + SLOT_SIZE, SLOT_HIGHLIGHT);
        if (hovered) {
            graphics.fill(x + 1, y + 1, x + SLOT_SIZE - 1, y + SLOT_SIZE - 1, HOVER_GLOW);
        }
    }

    private static String formatCount(long count) {
        if (count >= 1_000_000) return String.format("%.1fM", count / 1_000_000.0);
        if (count >= 1_000) return String.format("%.1fk", count / 1_000.0);
        return String.valueOf(count);
    }

    @Override
    public boolean isPauseScreen() {
        return false;
    }
}

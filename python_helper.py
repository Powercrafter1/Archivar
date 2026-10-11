import os
import json
from pathlib import Path

ARCHIVAR_DIR = Path(r"C:\Users\Ronny\OneDrive\Desktop\SurpriseMods\archivar")
BASE_DIR = Path(__file__).resolve().parent

if not (BASE_DIR / "src").exists() and ARCHIVAR_DIR.exists():
    BASE_DIR = ARCHIVAR_DIR

def write_file(relative_path: str, content: str):
    full_path = BASE_DIR / relative_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as f:
        f.write(content.strip() + "\n")
    print(f"[OK] Aktualisiert: {full_path}")

print("=== Archivar: Bugfix & AE2-Style Crafting Grid ohne Überlappung ===")

# -------------------------------------------------------------------------
# 1. ARCHIVAR DATA (Bugfix & 3x3 Crafting Grid Speicherung)
# -------------------------------------------------------------------------
write_file(
    "src/main/java/net/archivar/storage/ArchivarData.java",
    """
package net.archivar.storage;

import net.minecraft.core.HolderLookup;
import net.minecraft.core.NonNullList;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.nbt.ListTag;
import net.minecraft.nbt.Tag;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.ContainerHelper;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.saveddata.SavedData;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

public class ArchivarData extends SavedData {

    public static class Entry {
        public ItemStack template;
        public long count;

        public Entry(ItemStack template, long count) {
            this.template = template.copy();
            this.template.setCount(1);
            this.count = count;
        }
    }

    public static class Vault {
        public final List<Entry> items = new ArrayList<>();
        // Persistentes 3x3 Crafting-Gitter (bleibt beim Schließen erhalten!)
        public final NonNullList<ItemStack> craftingGrid = NonNullList.withSize(9, ItemStack.EMPTY);

        public synchronized void insert(ItemStack stack) {
            if (stack.isEmpty()) return;
            for (Entry e : items) {
                if (ItemStack.isSameItemSameComponents(e.template, stack)) {
                    e.count += stack.getCount();
                    return;
                }
            }
            items.add(new Entry(stack, stack.getCount()));
        }

        public synchronized ItemStack extract(ItemStack sample, int maxAmount) {
            for (Iterator<Entry> it = items.iterator(); it.hasNext(); ) {
                Entry e = it.next();
                if (ItemStack.isSameItemSameComponents(e.template, sample)) {
                    int toTake = (int) Math.min(e.count, maxAmount);
                    e.count -= toTake;
                    ItemStack out = e.template.copy();
                    out.setCount(toTake);
                    if (e.count <= 0) {
                        it.remove();
                    }
                    return out;
                }
            }
            return ItemStack.EMPTY;
        }

        public synchronized List<Entry> getAll() {
            return new ArrayList<>(items);
        }
    }

    private final Map<UUID, Vault> vaults = new ConcurrentHashMap<>();

    public ArchivarData() {
    }

    public static final SavedData.Factory<ArchivarData> FACTORY =
            new SavedData.Factory<>(ArchivarData::new, ArchivarData::load, null);

    public static ArchivarData get(MinecraftServer server) {
        return server.overworld().getDataStorage().computeIfAbsent(FACTORY, "archivar_storage");
    }

    public Vault getVault(ServerPlayer player) {
        UUID id = player.getUUID();
        if (player.server.isSingleplayer()) {
            id = UUID.fromString("00000000-0000-0000-0000-000000000000");
        }
        return vaults.computeIfAbsent(id, k -> new Vault());
    }

    public Vault getVault(UUID id) {
        return vaults.computeIfAbsent(id, k -> new Vault());
    }

    @Override
    public CompoundTag save(CompoundTag tag, HolderLookup.Provider registries) {
        ListTag vaultList = new ListTag();
        for (Map.Entry<UUID, Vault> en : vaults.entrySet()) {
            CompoundTag vTag = new CompoundTag();
            vTag.putUUID("owner", en.getKey());

            // 1. Archiv Items
            ListTag itemList = new ListTag();
            for (Entry entry : en.getValue().items) {
                CompoundTag itemTag = new CompoundTag();
                Tag savedItem = entry.template.saveOptional(registries);
                itemTag.put("item", savedItem);
                itemTag.putLong("count", entry.count);
                itemList.add(itemTag);
            }
            vTag.put("items", itemList);

            // 2. Crafting Grid Slots
            ContainerHelper.saveAllItems(vTag, en.getValue().craftingGrid, registries);

            vaultList.add(vTag);
        }
        tag.put("vaults", vaultList);
        return tag;
    }

    public static ArchivarData load(CompoundTag tag, HolderLookup.Provider registries) {
        ArchivarData data = new ArchivarData();
        ListTag vaultList = tag.getList("vaults", Tag.TAG_COMPOUND);
        for (int i = 0; i < vaultList.size(); i++) {
            CompoundTag vTag = vaultList.getCompound(i);
            if (!vTag.hasUUID("owner")) continue;
            UUID owner = vTag.getUUID("owner");
            Vault vault = new Vault();

            // 1. Archiv Items laden
            ListTag itemList = vTag.getList("items", Tag.TAG_COMPOUND);
            for (int j = 0; j < itemList.size(); j++) {
                CompoundTag iTag = itemList.getCompound(j);
                if (iTag.contains("item", Tag.TAG_COMPOUND)) {
                    ItemStack parsed = ItemStack.parseOptional(registries, iTag.getCompound("item"));
                    if (!parsed.isEmpty()) {
                        long count = iTag.getLong("count");
                        vault.items.add(new Entry(parsed, count));
                    }
                }
            }

            // 2. Crafting Grid laden
            ContainerHelper.loadAllItems(vTag, vault.craftingGrid, registries);

            data.vaults.put(owner, vault);
        }
        return data;
    }
}
"""
)

# -------------------------------------------------------------------------
# 2. ARCHIVAR PAYLOADS (Sync mit Crafting-Slots & Crafting-Aktionen)
# -------------------------------------------------------------------------
write_file(
    "src/main/java/net/archivar/network/ArchivarPayloads.java",
    """
package net.archivar.network;

import net.archivar.Archivar;
import net.minecraft.network.RegistryFriendlyByteBuf;
import net.minecraft.network.codec.ByteBufCodecs;
import net.minecraft.network.codec.StreamCodec;
import net.minecraft.network.protocol.common.custom.CustomPacketPayload;
import net.minecraft.world.item.ItemStack;

import java.util.ArrayList;
import java.util.List;

public final class ArchivarPayloads {
    private ArchivarPayloads() {}

    public record ItemEntry(ItemStack stack, long count) {
        public static final StreamCodec<RegistryFriendlyByteBuf, ItemEntry> STREAM_CODEC = StreamCodec.of(
                (buf, val) -> {
                    ItemStack.OPTIONAL_STREAM_CODEC.encode(buf, val.stack);
                    buf.writeVarLong(val.count);
                },
                buf -> new ItemEntry(ItemStack.OPTIONAL_STREAM_CODEC.decode(buf), buf.readVarLong())
        );
    }

    /** Server -> Client: Synchronisiert Lagerinhalte UND das 3x3 Crafting-Gitter */
    public record SyncTerminalPayload(List<ItemEntry> items, List<ItemStack> craftGrid) implements CustomPacketPayload {
        public static final Type<SyncTerminalPayload> TYPE = new Type<>(Archivar.id("sync_terminal"));
        public static final StreamCodec<RegistryFriendlyByteBuf, SyncTerminalPayload> STREAM_CODEC = StreamCodec.of(
                (buf, val) -> {
                    buf.writeVarInt(val.items.size());
                    for (ItemEntry e : val.items) {
                        ItemEntry.STREAM_CODEC.encode(buf, e);
                    }
                    buf.writeVarInt(val.craftGrid.size());
                    for (ItemStack s : val.craftGrid) {
                        ItemStack.OPTIONAL_STREAM_CODEC.encode(buf, s);
                    }
                },
                buf -> {
                    int size = buf.readVarInt();
                    List<ItemEntry> list = new ArrayList<>(size);
                    for (int i = 0; i < size; i++) {
                        list.add(ItemEntry.STREAM_CODEC.decode(buf));
                    }
                    int craftSize = buf.readVarInt();
                    List<ItemStack> craftList = new ArrayList<>(craftSize);
                    for (int i = 0; i < craftSize; i++) {
                        craftList.add(ItemStack.OPTIONAL_STREAM_CODEC.decode(buf));
                    }
                    return new SyncTerminalPayload(list, craftList);
                }
        );

        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record RequestOpenTerminalPayload() implements CustomPacketPayload {
        public static final Type<RequestOpenTerminalPayload> TYPE = new Type<>(Archivar.id("open_terminal"));
        public static final StreamCodec<RegistryFriendlyByteBuf, RequestOpenTerminalPayload> STREAM_CODEC = StreamCodec.unit(new RequestOpenTerminalPayload());
        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record ExtractItemPayload(ItemStack sample, int amount) implements CustomPacketPayload {
        public static final Type<ExtractItemPayload> TYPE = new Type<>(Archivar.id("extract_item"));
        public static final StreamCodec<RegistryFriendlyByteBuf, ExtractItemPayload> STREAM_CODEC = StreamCodec.composite(
                ItemStack.OPTIONAL_STREAM_CODEC, ExtractItemPayload::sample,
                ByteBufCodecs.VAR_INT, ExtractItemPayload::amount,
                ExtractItemPayload::new
        );
        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    public record InsertItemPayload(int slotIndex) implements CustomPacketPayload {
        public static final Type<InsertItemPayload> TYPE = new Type<>(Archivar.id("insert_item"));
        public static final StreamCodec<RegistryFriendlyByteBuf, InsertItemPayload> STREAM_CODEC = StreamCodec.composite(
                ByteBufCodecs.VAR_INT, InsertItemPayload::slotIndex,
                InsertItemPayload::new
        );
        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Client -> Server: Klick auf einen der 9 Crafting-Grid Slots (0..8) */
    public record ClickCraftSlotPayload(int slotIndex, int button, boolean shift) implements CustomPacketPayload {
        public static final Type<ClickCraftSlotPayload> TYPE = new Type<>(Archivar.id("click_craft_slot"));
        public static final StreamCodec<RegistryFriendlyByteBuf, ClickCraftSlotPayload> STREAM_CODEC = StreamCodec.composite(
                ByteBufCodecs.VAR_INT, ClickCraftSlotPayload::slotIndex,
                ByteBufCodecs.VAR_INT, ClickCraftSlotPayload::button,
                ByteBufCodecs.BOOL, ClickCraftSlotPayload::shift,
                ClickCraftSlotPayload::new
        );
        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Client -> Server: Klick auf den Crafting-Ergebnis-Slot */
    public record TakeCraftResultPayload(boolean shift) implements CustomPacketPayload {
        public static final Type<TakeCraftResultPayload> TYPE = new Type<>(Archivar.id("take_craft_result"));
        public static final StreamCodec<RegistryFriendlyByteBuf, TakeCraftResultPayload> STREAM_CODEC = StreamCodec.composite(
                ByteBufCodecs.BOOL, TakeCraftResultPayload::shift,
                TakeCraftResultPayload::new
        );
        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }

    /** Client -> Server: Räumt das 3x3 Gitter zurück ins Lager */
    public record ClearCraftGridPayload() implements CustomPacketPayload {
        public static final Type<ClearCraftGridPayload> TYPE = new Type<>(Archivar.id("clear_craft_grid"));
        public static final StreamCodec<RegistryFriendlyByteBuf, ClearCraftGridPayload> STREAM_CODEC = StreamCodec.unit(new ClearCraftGridPayload());
        @Override
        public Type<? extends CustomPacketPayload> type() { return TYPE; }
    }
}
"""
)

# -------------------------------------------------------------------------
# 3. ARCHIVAR HAUPTKLASSE (Server-seitige Crafting-Ausführung)
# -------------------------------------------------------------------------
write_file(
    "src/main/java/net/archivar/Archivar.java",
    """
package net.archivar;

import net.archivar.block.StorageInterfaceBlock;
import net.archivar.block.StorageInterfaceBlockEntity;
import net.archivar.network.ArchivarPayloads;
import net.archivar.storage.ArchivarData;
import net.fabricmc.api.ModInitializer;
import net.fabricmc.fabric.api.itemgroup.v1.ItemGroupEvents;
import net.fabricmc.fabric.api.networking.v1.PayloadTypeRegistry;
import net.fabricmc.fabric.api.networking.v1.ServerPlayNetworking;
import net.minecraft.core.NonNullList;
import net.minecraft.core.Registry;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.item.BlockItem;
import net.minecraft.world.item.CreativeModeTabs;
import net.minecraft.world.item.Item;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.crafting.*;
import net.minecraft.world.level.block.Block;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.BlockEntityType;
import net.minecraft.world.level.block.state.BlockBehaviour;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

public class Archivar implements ModInitializer {
    public static final String MOD_ID = "archivar";
    public static final Logger LOGGER = LoggerFactory.getLogger(MOD_ID);

    public static ResourceLocation id(String path) {
        return ResourceLocation.fromNamespaceAndPath(MOD_ID, path);
    }

    public static final Block STORAGE_INTERFACE = new StorageInterfaceBlock(
            BlockBehaviour.Properties.ofFullCopy(Blocks.IRON_BLOCK).noOcclusion()
    );
    public static final BlockItem STORAGE_INTERFACE_ITEM = new BlockItem(STORAGE_INTERFACE, new Item.Properties());
    public static BlockEntityType<StorageInterfaceBlockEntity> STORAGE_INTERFACE_BE;

    @Override
    public void onInitialize() {
        Registry.register(BuiltInRegistries.BLOCK, id("storage_interface"), STORAGE_INTERFACE);
        Registry.register(BuiltInRegistries.ITEM, id("storage_interface"), STORAGE_INTERFACE_ITEM);

        STORAGE_INTERFACE_BE = Registry.register(
                BuiltInRegistries.BLOCK_ENTITY_TYPE,
                id("storage_interface"),
                BlockEntityType.Builder.of(StorageInterfaceBlockEntity::new, STORAGE_INTERFACE).build()
        );

        ItemGroupEvents.modifyEntriesEvent(CreativeModeTabs.FUNCTIONAL_BLOCKS).register(entries -> {
            entries.accept(STORAGE_INTERFACE_ITEM);
        });

        // Payloads
        PayloadTypeRegistry.playS2C().register(ArchivarPayloads.SyncTerminalPayload.TYPE, ArchivarPayloads.SyncTerminalPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.RequestOpenTerminalPayload.TYPE, ArchivarPayloads.RequestOpenTerminalPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.ExtractItemPayload.TYPE, ArchivarPayloads.ExtractItemPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.InsertItemPayload.TYPE, ArchivarPayloads.InsertItemPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.ClickCraftSlotPayload.TYPE, ArchivarPayloads.ClickCraftSlotPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.TakeCraftResultPayload.TYPE, ArchivarPayloads.TakeCraftResultPayload.STREAM_CODEC);
        PayloadTypeRegistry.playC2S().register(ArchivarPayloads.ClearCraftGridPayload.TYPE, ArchivarPayloads.ClearCraftGridPayload.STREAM_CODEC);

        // Terminal Öffnen
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.RequestOpenTerminalPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> syncAndOpenTerminal(context.player()));
        });

        // Item Entnehmen
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.ExtractItemPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);
                ItemStack extracted = vault.extract(payload.sample(), payload.amount());
                if (!extracted.isEmpty()) {
                    if (!sp.getInventory().add(extracted)) {
                        sp.drop(extracted, false);
                    }
                    syncAndOpenTerminal(sp);
                }
            });
        });

        // Item Einzahlen
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.InsertItemPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                if (payload.slotIndex() >= 0 && payload.slotIndex() < sp.getInventory().items.size()) {
                    ItemStack inSlot = sp.getInventory().items.get(payload.slotIndex());
                    if (!inSlot.isEmpty()) {
                        ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);
                        vault.insert(inSlot.copy());
                        inSlot.setCount(0);
                        syncAndOpenTerminal(sp);
                    }
                }
            });
        });

        // Klick auf Crafting-Slot (Zutaten setzen/herausnehmen)
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.ClickCraftSlotPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);
                int slot = payload.slotIndex();
                if (slot >= 0 && slot < 9) {
                    ItemStack inSlot = vault.craftingGrid.get(slot);
                    if (payload.shift()) {
                        // Shift-Klick: Zutat direkt zurück ins Archiv
                        if (!inSlot.isEmpty()) {
                            vault.insert(inSlot.copy());
                            vault.craftingGrid.set(slot, ItemStack.EMPTY);
                        }
                    } else if (payload.button() == 1) {
                        // Rechtsklick: 1 Item entnehmen und ins Inventar
                        if (!inSlot.isEmpty()) {
                            ItemStack taken = inSlot.split(1);
                            if (!sp.getInventory().add(taken)) {
                                sp.drop(taken, false);
                            }
                            if (inSlot.isEmpty()) {
                                vault.craftingGrid.set(slot, ItemStack.EMPTY);
                            }
                        }
                    } else {
                        // Linksklick: Ganzen Slot ins Inventar nehmen
                        if (!inSlot.isEmpty()) {
                            if (!sp.getInventory().add(inSlot.copy())) {
                                sp.drop(inSlot, false);
                            }
                            vault.craftingGrid.set(slot, ItemStack.EMPTY);
                        }
                    }
                    syncAndOpenTerminal(sp);
                }
            });
        });

        // Crafting-Ergebnis herstellen
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.TakeCraftResultPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);

                do {
                    CraftingInput input = CraftingInput.of(3, 3, vault.craftingGrid);
                    Optional<RecipeHolder<CraftingRecipe>> match = sp.server.getRecipeManager()
                            .getRecipeFor(RecipeType.CRAFTING, input, sp.serverLevel());

                    if (match.isEmpty()) break;

                    ItemStack result = match.get().value().assemble(input, sp.server.registryAccess());
                    if (result.isEmpty()) break;

                    // Platz im Spielerinventar prüfen
                    if (!sp.getInventory().canPlaceItem(0, result) && sp.getInventory().getFreeSlot() == -1) {
                        break;
                    }

                    // 1 Zutat aus jedem belegten Slot abziehen
                    NonNullList<ItemStack> remaining = match.get().value().getRemainingItems(input);
                    for (int i = 0; i < 9; i++) {
                        ItemStack current = vault.craftingGrid.get(i);
                        if (!current.isEmpty()) {
                            current.shrink(1);
                        }
                        if (!remaining.get(i).isEmpty()) {
                            if (current.isEmpty()) {
                                vault.craftingGrid.set(i, remaining.get(i));
                            } else {
                                vault.insert(remaining.get(i));
                            }
                        }
                    }

                    if (!sp.getInventory().add(result)) {
                        sp.drop(result, false);
                    }

                } while (payload.shift()); // Wenn Shift: Solange craften, wie Zutaten da sind!

                syncAndOpenTerminal(sp);
            });
        });

        // Crafting-Gitter leeren
        ServerPlayNetworking.registerGlobalReceiver(ArchivarPayloads.ClearCraftGridPayload.TYPE, (payload, context) -> {
            context.player().server.execute(() -> {
                ServerPlayer sp = context.player();
                ArchivarData.Vault vault = ArchivarData.get(sp.server).getVault(sp);
                for (int i = 0; i < 9; i++) {
                    ItemStack stack = vault.craftingGrid.get(i);
                    if (!stack.isEmpty()) {
                        vault.insert(stack.copy());
                        vault.craftingGrid.set(i, ItemStack.EMPTY);
                    }
                }
                syncAndOpenTerminal(sp);
            });
        });

        LOGGER.info("Archivar Lagermod mit AE2-Crafting geladen!");
    }

    public static void syncAndOpenTerminal(ServerPlayer player) {
        ArchivarData.Vault vault = ArchivarData.get(player.server).getVault(player);
        List<ArchivarPayloads.ItemEntry> entries = vault.getAll().stream()
                .map(e -> new ArchivarPayloads.ItemEntry(e.template, e.count))
                .toList();
        List<ItemStack> craftGrid = new ArrayList<>(vault.craftingGrid);
        ServerPlayNetworking.send(player, new ArchivarPayloads.SyncTerminalPayload(entries, craftGrid));
    }
}
"""
)

# -------------------------------------------------------------------------
# 4. ARCHIVAR TERMINAL SCREEN (Perfekt getrennte Zonen, 0% Überlappung)
# -------------------------------------------------------------------------
write_file(
    "src/main/java/net/archivar/client/ArchivarTerminalScreen.java",
    """
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
"""
)

# -------------------------------------------------------------------------
# 5. ARCHIVAR CLIENT ENTRYPOINT (Unterstützt craftGrid im Sync)
# -------------------------------------------------------------------------
write_file(
    "src/main/java/net/archivar/client/ArchivarClient.java",
    """
package net.archivar.client;

import com.mojang.blaze3d.platform.InputConstants;
import net.archivar.network.ArchivarPayloads;
import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.fabricmc.fabric.api.client.networking.v1.ClientPlayNetworking;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import org.lwjgl.glfw.GLFW;

public class ArchivarClient implements ClientModInitializer {
    public static KeyMapping openTerminalKey;

    @Override
    public void onInitializeClient() {
        openTerminalKey = KeyBindingHelper.registerKeyBinding(new KeyMapping(
                "key.archivar.open_terminal",
                InputConstants.Type.KEYSYM,
                GLFW.GLFW_KEY_K,
                "category.archivar.general"
        ));

        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            while (openTerminalKey.consumeClick()) {
                if (client.player != null) {
                    ClientPlayNetworking.send(new ArchivarPayloads.RequestOpenTerminalPayload());
                }
            }
        });

        ClientPlayNetworking.registerGlobalReceiver(ArchivarPayloads.SyncTerminalPayload.TYPE, (payload, context) -> {
            context.client().execute(() -> {
                Minecraft mc = Minecraft.getInstance();
                if (mc.screen instanceof ArchivarTerminalScreen current) {
                    current.updateData(payload.items(), payload.craftGrid());
                } else {
                    mc.setScreen(new ArchivarTerminalScreen(payload.items(), payload.craftGrid()));
                }
            });
        });
    }
}
"""
)

# -------------------------------------------------------------------------
# 6. SPRACHDATEIEN (Texte für Crafting & Buttons)
# -------------------------------------------------------------------------
de_lang = {
    "block.archivar.storage_interface": "Lager-Anschluss (Interface)",
    "key.archivar.open_terminal": "Archiv-Terminal öffnen",
    "category.archivar.general": "Archivar",
    "gui.archivar.terminal_title": "Archivar — Crafting Terminal",
    "gui.archivar.crafting": "Crafting",
    "gui.archivar.clear": "Leeren",
    "gui.archivar.inventory": "Spieler-Inventar",
    "message.archivar.interface_info": "§b[Archivar] §7Lager-Anschluss aktiv. Schließe Trichter oder Rohre an, um Items direkt ins Archiv zu leiten."
}
write_file("src/main/resources/assets/archivar/lang/de_de.json", json.dumps(de_lang, indent=2, ensure_ascii=False))

en_lang = {
    "block.archivar.storage_interface": "Storage Interface",
    "key.archivar.open_terminal": "Open Archive Terminal",
    "category.archivar.general": "Archivar",
    "gui.archivar.terminal_title": "Archivar — Crafting Terminal",
    "gui.archivar.crafting": "Crafting",
    "gui.archivar.clear": "Clear",
    "gui.archivar.inventory": "Player Inventory",
    "message.archivar.interface_info": "§b[Archivar] §7Storage Interface active. Connect hoppers or pipes to pump items into the archive."
}
write_file("src/main/resources/assets/archivar/lang/en_us.json", json.dumps(en_lang, indent=2))

print("\n=== Update fertig! Starte jetzt runClient im Gradle-Widget. ===")
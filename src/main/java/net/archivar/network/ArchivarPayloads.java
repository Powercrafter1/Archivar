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

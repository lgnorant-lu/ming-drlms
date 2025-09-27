from __future__ import annotations

import flet as ft
import time
import threading
from .theme import spacing, pixel_text


def create_seed_progress(initial_value: float = 0.0) -> ft.Container:
    """Create a seed progress bar container with pixel art image stages."""

    # State holder
    class ProgressState:
        def __init__(self):
            self.value = initial_value
            # Use image instead of emoji for better visual consistency
            self.stage_image = ft.Image(
                src="src/ming_drlms_gui/assets/images/progress/stage_0_water.png",
                width=48,  # Fixed size for all images
                height=48,
                fit=ft.ImageFit.CONTAIN,
            )
            self.progress_bar = ft.ProgressBar(
                value=initial_value,
                height=16,  # Taller progress bar
                color="#4CAF50",
                bgcolor="#E8F5E8",
                border_radius=8,
            )
            self.percent_text = pixel_text(
                f"{int(initial_value * 100)}%", 14, "primary"
            )
            self._completed = False

        def update_stage_image(self, progress: float):
            """Update the stage image based on progress."""
            # Map progress to image stages
            if progress >= 0.9:
                image_src = (
                    "src/ming_drlms_gui/assets/images/progress/stage_5_mature_tree.png"
                )
            elif progress >= 0.7:
                image_src = (
                    "src/ming_drlms_gui/assets/images/progress/stage_4_young_tree.png"
                )
            elif progress >= 0.5:
                image_src = (
                    "src/ming_drlms_gui/assets/images/progress/stage_3_sapling.png"
                )
            elif progress >= 0.3:
                image_src = (
                    "src/ming_drlms_gui/assets/images/progress/stage_2_sprout.png"
                )
            elif progress >= 0.1:
                image_src = "src/ming_drlms_gui/assets/images/progress/stage_1_seed.png"
            else:
                image_src = (
                    "src/ming_drlms_gui/assets/images/progress/stage_0_water.png"
                )

            self.stage_image.src = image_src

    state = ProgressState()

    def update_progress(value: float):
        """Update progress value and growth stage with image switching."""
        state.value = max(0.0, min(1.0, value))

        # Update stage image based on progress
        state.update_stage_image(state.value)

        # Update progress bar
        state.progress_bar.value = state.value
        state.percent_text.value = f"{int(state.value * 100)}%"

        # Add sparkle effect for completion
        if state.value >= 1.0 and not state._completed:
            state._completed = True

            def sparkle():
                try:
                    # Create sparkle overlay positioned over the stage image
                    sparkle_overlay = ft.Container(
                        content=ft.Image(
                            src="src/ming_drlms_gui/assets/images/progress/effect_sparkle_spritesheet.png",
                            width=48,
                            height=48,
                            fit=ft.ImageFit.CONTAIN,
                        ),
                        width=48,
                        height=48,
                        alignment=ft.alignment.center,
                    )

                    # Add sparkle overlay to the main row (over the stage image)
                    main_row = container.content.content.children[0]
                    main_row.controls.append(sparkle_overlay)
                    container.update()

                    # Animate sparkle effect - cycle through spritesheet frames
                    # frame_width = 48  # not used
                    # frame_height = 48  # not used
                    frames = [
                        (0, 0),
                        (48, 0),
                        (0, 48),
                        (48, 48),
                    ]  # 4 frames in 2x2 grid

                    for frame_index in range(
                        len(frames) * 2
                    ):  # Play twice for better effect
                        frame = frames[frame_index % len(frames)]
                        sparkle_overlay.content.src_left = frame[0]
                        sparkle_overlay.content.src_top = frame[1]
                        time.sleep(0.12)  # 120ms per frame

                    # Remove sparkle after animation
                    if sparkle_overlay in main_row.controls:
                        main_row.controls.remove(sparkle_overlay)
                        container.update()

                except Exception:
                    # Silently handle sparkle errors - non-critical feature
                    pass

            threading.Thread(target=sparkle, daemon=True).start()

    # Create animated container
    container = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        state.stage_image,
                        ft.Container(
                            content=ft.Column(
                                [
                                    state.progress_bar,
                                    state.percent_text,
                                ],
                                spacing=6,
                                tight=True,
                            ),
                            width=220,  # Wider container
                        ),
                    ],
                    spacing=spacing(2),
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                # Add growth description text
                pixel_text("种子正在生长...", 12, "muted"),
            ],
            spacing=spacing(2),
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=spacing(3),
        border_radius=16,
        bgcolor="#ffffff",
        border=ft.border.all(3, "#4CAF50"),
        shadow=ft.BoxShadow(
            spread_radius=2,
            blur_radius=12,
            color="#4CAF50,0.4",
            offset=ft.Offset(0, 4),
        ),
    )

    # Attach update method to container
    container.update_progress = update_progress

    return container

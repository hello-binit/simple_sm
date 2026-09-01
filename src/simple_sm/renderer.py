import os
import math
from typing import Any, Dict, List, Tuple
from PIL import Image, ImageDraw, ImageFont


def get_font(size: int = 12, bold: bool = True) -> ImageFont.ImageFont:
    """Retrieves a high-quality system font, falling back to the default Pillow font."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans.ttf",
        "Arial.ttf"
    ]
    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def bezier_curve(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    num_points: int = 20,
) -> List[Tuple[float, float]]:
    """Generates a smooth quadratic bezier curve between p0 and p2 using control point p1."""
    points = []
    for i in range(num_points + 1):
        t = i / num_points
        x = (1 - t)**2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
        y = (1 - t)**2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
        points.append((x, y))
    return points


def draw_arrowhead(
    draw: ImageDraw.ImageDraw,
    end_point: Tuple[float, float],
    direction_vector: Tuple[float, float],
    color: Tuple[int, int, int],
    size: float = 10.0,
) -> None:
    """Draws a solid arrowhead pointing in direction_vector at end_point."""
    dx, dy = direction_vector
    length = math.sqrt(dx**2 + dy**2)
    if length == 0:
        return
    ux = dx / length
    uy = dy / length

    p_tip = end_point
    p_base = (end_point[0] - ux * size, end_point[1] - uy * size)
    p_left = (p_base[0] - uy * size * 0.5, p_base[1] + ux * size * 0.5)
    p_right = (p_base[0] + uy * size * 0.5, p_base[1] - ux * size * 0.5)

    draw.polygon([p_tip, p_left, p_right], fill=color)


class StateMachineRenderer:
    """A pure-Python visualizer that renders simple_sm state machines to PIL Images.
    """

    def __init__(self, machine: Any):
        self.machine = machine
        self.states = list(machine._states_enum)

    def render(self) -> Image.Image:
        """Renders the state machine to a PIL Image with transition highlights."""
        # 1. Define dimensions and layout parameters
        width = 500
        height = 70 + len(self.states) * 110
        img = Image.new("RGB", (width, height), (255, 255, 255))
        draw = ImageDraw.Draw(img)

        # Draw a subtle background grid or border
        draw.rectangle([5, 5, width - 6, height - 6], outline=(230, 235, 240), width=2)

        # 2. Compute state node positions (vertical sequence)
        node_w = 260
        node_h = 50
        center_x = width // 2
        node_positions: Dict[Any, Tuple[float, float]] = {}

        for idx, state in enumerate(self.states):
            cy = 75 + idx * 110
            node_positions[state] = (center_x, cy)

        # Draw Start Marker [*]
        start_cy = 20
        draw.ellipse([center_x - 8, start_cy - 8, center_x + 8, start_cy + 8], fill=(30, 41, 59))
        # Arrow pointing from [*] to first state top edge
        first_state_pos = node_positions[self.states[0]]
        first_state_top = (first_state_pos[0], first_state_pos[1] - node_h // 2)
        draw.line([(center_x, start_cy + 8), first_state_top], fill=(71, 85, 105), width=2)
        draw_arrowhead(draw, first_state_top, (0, 1), (71, 85, 105), size=8)

        # Fonts
        font_node = get_font(13, bold=True)
        font_label = get_font(11, bold=False)

        # 3. Draw Transitions (Edges)
        last_transition = self.machine._last_transition
        active_color = (0, 123, 255)  # Gorgeous active blue
        normal_color = (148, 163, 184)  # Slate gray

        # Gather transition pairs
        for trigger, sources in self.machine._transitions.items():
            for src, dest in sources.items():
                is_active = (
                    last_transition
                    and last_transition["trigger"] == trigger
                    and last_transition["source"] == src
                    and last_transition["dest"] == dest
                )
                edge_color = active_color if is_active else normal_color
                edge_width = 3 if is_active else 1

                p1 = node_positions[src]
                p2 = node_positions[dest]
                src_idx = self.states.index(src)
                dest_idx = self.states.index(dest)

                # Determine edge route
                if dest_idx == src_idx + 1:
                    # Sequential forward neighbor: straight vertical line
                    line_start = (p1[0], p1[1] + node_h // 2)
                    line_end = (p2[0], p2[1] - node_h // 2)
                    draw.line([line_start, line_end], fill=edge_color, width=edge_width)
                    draw_arrowhead(draw, line_end, (0, 1), edge_color, size=9)

                    # Label at midpoint
                    mid_x = center_x
                    mid_y = (line_start[1] + line_end[1]) // 2
                    self._draw_label(draw, trigger, (mid_x, mid_y), font_label, edge_color)

                elif dest_idx > src_idx + 1:
                    # Forward jump: bow out to the left
                    offset = 70 + (dest_idx - src_idx) * 10
                    p_start = (p1[0] - node_w // 2, p1[1])
                    p_end = (p2[0] - node_w // 2, p2[1])
                    p_ctrl = (center_x - node_w // 2 - offset, (p1[1] + p2[1]) // 2)

                    points = bezier_curve(p_start, p_ctrl, p_end)
                    # Draw curve
                    for i in range(len(points) - 1):
                        draw.line([points[i], points[i + 1]], fill=edge_color, width=edge_width)

                    # Arrowhead at end
                    tangent = (points[-1][0] - points[-2][0], points[-1][1] - points[-2][1])
                    draw_arrowhead(draw, p_end, tangent, edge_color, size=9)

                    # Label at midpoint of curve
                    mid_point = points[len(points) // 2]
                    self._draw_label(draw, trigger, mid_point, font_label, edge_color)

                else:
                    # Backward jump (abort/reset): bow out to the right
                    offset = 70 + (src_idx - dest_idx) * 10
                    p_start = (p1[0] + node_w // 2, p1[1])
                    p_end = (p2[0] + node_w // 2, p2[1])
                    p_ctrl = (center_x + node_w // 2 + offset, (p1[1] + p2[1]) // 2)

                    points = bezier_curve(p_start, p_ctrl, p_end)
                    # Draw curve
                    for i in range(len(points) - 1):
                        draw.line([points[i], points[i + 1]], fill=edge_color, width=edge_width)

                    # Arrowhead at end
                    tangent = (points[-1][0] - points[-2][0], points[-1][1] - points[-2][1])
                    draw_arrowhead(draw, p_end, tangent, edge_color, size=9)

                    # Label at midpoint of curve
                    mid_point = points[len(points) // 2]
                    self._draw_label(draw, trigger, mid_point, font_label, edge_color)

        # 4. Draw State Nodes (Rectangles)
        current_state = self.machine.state
        for state, (cx, cy) in node_positions.items():
            is_active = state == current_state

            # Modern style colors
            if is_active:
                fill_color = (211, 232, 211) # light green
                outline_color = (0, 123, 62) # dark green border
                text_color = (0, 123, 62) # dark green text
                border_width = 3
            else:
                fill_color = (248, 250, 252)  # Clean white/gray background
                outline_color = (100, 116, 139)  # Cool gray border
                text_color = (30, 41, 59)  # Dark slate text
                border_width = 1

            # Draw Rounded Rectangle
            rx1 = cx - node_w // 2
            ry1 = cy - node_h // 2
            rx2 = cx + node_w // 2
            ry2 = cy + node_h // 2

            draw.rounded_rectangle(
                [rx1, ry1, rx2, ry2],
                radius=8,
                fill=fill_color,
                outline=outline_color,
                width=border_width,
            )

            # Center text inside node
            text = state.name
            bbox = draw.textbbox((0, 0), text, font=font_node)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text((cx - tw // 2, cy - th // 2 - bbox[1]), text, fill=text_color, font=font_node)

        return img

    def _draw_label(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        pos: Tuple[float, float],
        font: ImageFont.ImageFont,
        color: Tuple[int, int, int],
    ) -> None:
        """Helper to render a text label with a semi-opaque background box to prevent overlap."""
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

        padding = 3
        rx1 = pos[0] - tw // 2 - padding
        ry1 = pos[1] - th // 2 - padding
        rx2 = pos[0] + tw // 2 + padding
        ry2 = pos[1] + th // 2 + padding

        # Clean background overlay box
        draw.rectangle([rx1, ry1, rx2, ry2], fill=(255, 255, 255))
        draw.text((pos[0] - tw // 2, pos[1] - th // 2 - bbox[1]), text, fill=color, font=font)
